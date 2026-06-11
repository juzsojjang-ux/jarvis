# 설계: 두뇌 추상화 (멀티 프로바이더 토대)

날짜: 2026-06-12
상태: 사용자 승인됨("추천대로 두뇌 추상화부터, 물어보지 말고 순차 진행")
선행: 없음(순수 추가). 후속: Gemini 어댑터 → GPT 어댑터 → 첫 실행 UI

## 목표

첫 실행에서 두뇌 프로바이더를 **하나** 고른다(Claude / Gemini / GPT). 동시 멀티
LLM이 아니라 **택1**. 이 sub-project는 그 **이음새(seam)만** 만든다 — 정식 두뇌
인터페이스 + 프로바이더 선택 설정 + 팩토리 디스패치. 실제 Gemini/GPT 구현은
다음 sub-project(이 이음새에 끼워 넣는다).

## 두뇌 계약 (오케스트레이터·remote·interpret가 의존)

조사로 확정한 실제 사용 표면(orchestrator.py·__main__.py):
- `async def respond(user_text: str) -> AsyncIterator[str]` — 발화할 영어를
  스트리밍 yield. 답 끝에 `[KO] <한국어>` 마커를 붙여 자막 분리(두뇌가 채움).
- `async def warm() -> None` — 부팅 예열(best-effort).
- `async def translate(text: str, target_lang: str) -> str` — 통역 1회 번역.
- `async def warm_interpret() -> None` — 통역 토글 시 예열(**옵션**, hasattr 가드).
- `async def close() -> None` — 종료 정리.
- `last_subtitle: str` — 마지막 답의 한국어 자막(HUD가 읽음).
- `remote_mode: bool` — 원격 턴 표시(**옵션**, hasattr 가드). 파괴 도구 차단에 사용.

## 컴포넌트

### `jarvis/brain/base.py` — Brain 프로토콜
- `typing.Protocol`(runtime_checkable)로 `Brain` 정의 — 위 7개 멤버를 문서화한
  계약. 어댑터(Claude/Gemini/GPT)가 구조적으로 conform하면 된다(상속 불필요).
- `BRAIN_PROVIDERS = ("claude", "gemini", "gpt")` 상수.
- `respond`의 `[KO]` 규약을 docstring으로 명시 — 어댑터 작성자가 지켜야 할 한 줄.
- 헬퍼 `split_ko(full_text) -> tuple[str, str]`: `[KO]` 마커로 (영어, 한국어)
  분리. subscription.py가 인라인으로 하던 파싱을 공용화 — Gemini/GPT 어댑터가
  재사용(중복 방지). subscription.py는 이번엔 안 건드리고(리스크 0), 어댑터들이
  이 헬퍼를 쓴다.

### `jarvis/core/config.py` — 프로바이더 선택
- `brain_provider: str = "claude"` — 첫 실행에서 정해지는 택1 값.
- 기존 `brain_backend`(="subscription"|"api")는 **Claude 내부** 구분으로 보존.
  매핑: provider="claude" → 기존 backend 로직(subscription 기본). provider=
  "gemini"/"gpt" → 해당 어댑터.
- 첫 실행 여부는 후속 UI sub-project가 persist(여기선 기본값만).

### `jarvis/brain/factory.py` — 디스패치 확장
- `make_brain`이 `brain_provider`를 먼저 본다:
  - "claude" → 기존 경로(brain_backend로 subscription/api 분기) 그대로.
  - "gemini" → `from .gemini import GeminiBrain` (아직 없음 → 다음 sub-project).
  - "gpt" → `from .openai_brain import GptBrain` (아직 없음).
  - 미구현 프로바이더는 명확한 한국어 안내와 함께 `NotImplementedError`:
    "Gemini 두뇌는 곧 추가됩니다. 지금은 Claude로 실행하세요." — 이음새는 준비됐고
    구현만 끼우면 됨을 분명히.
- back-compat: `brain_provider` 미설정(구버전 설정)이면 "claude"로 간주.

## 에러 처리
- 알 수 없는 provider → ValueError(명확 메시지).
- 미구현 provider(gemini/gpt) → NotImplementedError(안내 문자열).

## 테스트
- `Brain` 프로토콜: `SubscriptionBrain` 인스턴스가 `isinstance(b, Brain)`(runtime_
  checkable) True — 기존 두뇌가 계약을 만족함을 고정.
- `split_ko`: 마커 있음/없음/중복 안전.
- `make_brain`: provider="claude" → SubscriptionBrain(기존), 미설정 → claude,
  "gemini"/"gpt" → NotImplementedError(안내 포함), 잘못된 값 → ValueError.
- config: `brain_provider` 기본 "claude".

## 비범위(다음 sub-project)
- 실제 GeminiBrain/GptBrain 구현(함수호출 루프 + 권한 게이트 재구현).
- 첫 실행 선택/로그인 UI.
- API 키 저장(keyring) — UI sub-project에서.
