# 자비스 속도 개선 — 설계 (체감 최적화, 깊이 유지)

작성 2026-06-14 · 상태: 확정(자율 진행 승인) · 범위: `jarvis/__main__.py`, `jarvis/core/orchestrator.py`

## 결정 (브레인스토밍)

사고 예산(`think_budget_normal=4000`)은 **그대로 유지**(깊이 보존 — 이전 "두뇌 더 깊게" 요청 존중).
12초 첫문장은 콜드스타트가 아니라 tool-heavy 쿼리였고, warm은 이미 ready 전에 끝나 있었음.
**진짜 체감 지연은 "구동 속도"** — `__main__`이 `brain.warm()`(콜드 claude CLI + throwaway 'hi' 쿼리 ~10s)을
"준비 완료" 전에 await 해 부팅을 ~10초 막는다.

## 변경

1. **두뇌 예열 백그라운드화** (`__main__`): `brain.warm()`을 await하지 않고
   `orch._warm_task = asyncio.create_task(orch.brain.warm())`로 띄운다. "준비 완료"가 즉시 출력 →
   구동 체감 ~10초 단축. `warm_phrases()`(로컬 TTS, 빠름)는 그대로 await(첫 필러 즉시성 보장).
   음성 모델 warm(stt/tts/vc)도 그대로(로컬·검증된 경로, 안전 우선).

2. **첫 턴이 예열을 1회 대기** (`orchestrator`): 새 헬퍼 `_await_warm()` —
   `self._warm_task`가 살아있으면 await(예외 무시), 끝났으면 즉시 통과. brain.respond 호출 **3경로**
   (_produce/voice, remote_turn, 백그라운드 작업) 시작부에서 호출. 이렇게 하면:
   - 첫 대화 턴은 warm 완료 후 실행 → 예열 이득 그대로(콜드 안 먹음).
   - warm의 throwaway 쿼리와 실제 쿼리가 **겹치지 않음**(현재 불변식 보존 — 동시 사용 레이스 차단).
   - 둘째 턴부터는 warm이 끝나 있어 `_await_warm()`이 즉시 통과(0지연).
   - 대기 중 음성 공백은 기존 `_delayed_ack`(0.9s 후 "잠시만요")가 덮음.

## 비목표(YAGNI / 위험 회피)

- 사고 예산 축소(깊이 손실) — 안 함.
- 프리미어 외부 MCP 제거 — 사용자가 의도적으로 설정(`~/.jarvis/mcp.json`). warm이 백그라운드라
  부팅을 안 막으므로 건드릴 이유 없음. 그대로 둠.
- 음성 모델 warm 병렬화 — 위험 대비 이득 작아 보류.
- 검색 자체 단축 — 외부 API 한계.

## 맥·윈도우 호환

전부 asyncio 태스크/표준 라이브러리. OS 분기 없음. CI 양쪽(macos/windows) 테스트로 검증.

## 검증

- 단위 테스트: `_await_warm()`가 (a) 태스크 None/완료 시 즉시 반환 (b) 미완료 태스크를 대기
  (c) 태스크 예외를 삼킴. 가짜 brain.warm으로 부팅이 warm을 안 막는지(즉시 ready) 확인.
- 전체 스위트 회귀 + 실기 부팅으로 "준비 완료"가 빨리 뜨는지 육안.
