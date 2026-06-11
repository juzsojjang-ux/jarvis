# 설계: 아이폰 원격 명령 (자비스 확장)

날짜: 2026-06-11
상태: 사용자 승인됨("아이폰 연동 한번 해보자" + "알아서 다 해")
선행: 로드맵 ①~④ 완료, 자비스 가동 중

## 목표

밖에서(또는 방 건너에서) 아이폰으로 자비스에게 명령을 보내고 답을 받는다.
아이폰 단축어(받아쓰기/텍스트) → 맥의 자비스 → 텍스트 답장. Siri가 "자비스"
단축어를 실행해 사실상 음성으로도 동작.

## 접근 선택

- **A. 인프로세스 HTTP + 단축어 (채택)** — orb_server(stdlib ThreadingHTTPServer)
  패턴 재사용. 실행 중인 두뇌(워밍된 영속 세션)를 그대로 써 즉시 응답.
- B. SSH+CLI — 매 호출 새 프로세스 = 두뇌 콜드스타트 ~10초. 탈락.
- C. iMessage 폴링 — 어디서나 되지만 자동발송 권한+폴링 지연. 차후 옵션.

## 아키텍처

```
아이폰 단축어("자비스")
  받아쓰기 → POST http://<맥주소>:8790/ask
             Authorization: Bearer <토큰>, JSON {"text": "..."}
→ jarvis/remote/server.py (스레드, stdlib)
  토큰 검증 → asyncio.run_coroutine_threadsafe(orch.remote_turn(text), loop)
→ Orchestrator.remote_turn: IDLE 게이트 → THINKING(음성 차단) → 두뇌 수집
→ JSON {"reply": 한국어, "reply_en": 영어} → 단축어가 표시/낭독
```

## 컴포넌트

### `jarvis/remote/server.py` — RemoteServer
- `RemoteServer(handler, host, port, token)` — `handler(text) -> dict`는
  주입(테스트는 가짜). `start()`/`stop()`. orb_server처럼 데몬 스레드,
  부팅을 절대 막지 않는다(포트 충돌 등 실패 시 안내만 출력).
- `POST /ask`만 처리. 그 외 경로/메서드 404.
- 인증: `Authorization: Bearer <token>` 정확 일치(`hmac.compare_digest`).
  불일치/부재 → 401, 본문 없음(정보 누설 금지).
- 본문: JSON `{"text": str}`. 빈 text → 400. 처리 결과 200 JSON.
- 핸들러 예외 → 500 `{"reply": "처리 중 오류가 났습니다."}`.
- 타임아웃: 핸들러 결과 대기 120초 → 504 `{"reply": "응답이 너무 오래 걸립니다."}`.
- `__main__`이 `asyncio.run_coroutine_threadsafe`로 루프에 던지는 브리지
  클로저를 만들어 주입한다(서버 모듈은 asyncio를 모름 — orb_server와 동일
  철학).

### 토큰 — `jarvis/remote/token.py`
- `load_or_create_token(path=~/.jarvis/remote_token) -> str`:
  파일 있으면 읽고, 없으면 `secrets.token_urlsafe(32)` 생성 후 0600으로 저장.
- 부팅 배너에 토큰을 그대로 출력하지 않는다 — 파일 경로만 안내
  ("[원격] http://<IP>:8790/ask — 토큰: ~/.jarvis/remote_token").

### `Orchestrator.remote_turn(text) -> dict`
- 게이트: `_can_announce()`(IDLE + 태스크 없음)가 아니면 즉시
  `{"reply": "지금 다른 일을 처리하고 있습니다. 잠시 후 다시 시도해 주세요."}`.
- 진행: `state=THINKING` + publish("thinking") — 웨이크 게이트가 IDLE만
  통과시키므로 음성 턴과의 동시 두뇌 사용(응답 훔치기 레이스)이 차단된다.
  try/finally로 `_to_idle()` 복귀.
- 두뇌: `brain.respond(text)` 전부 수집(**TTS 미사용 — 사용자 부재, 맥에서
  소리내지 않음**). 반환 `{"reply": last_subtitle(한국어) 없으면 영어 본문,
  "reply_en": 영어 본문}`.
- 원격 모드 플래그: 시작 시 `brain.remote_mode=True`, finally에서 False
  (hasattr 가드 — api 두뇌 호환).

### 보안 (3중)
1. **토큰**: 없으면 401. LAN 평문 HTTP는 집 안 위협모델에서 수용,
   외부는 Tailscale 권장(문서) — 포트포워딩 비권장.
2. **파괴 도구 원천 차단**: `_can_use_tool`에서 `self.remote_mode`이면
   confirm을 부르지 않고 즉시 Deny("원격에서는 실행할 수 없습니다") —
   원격엔 음성 확인 채널이 없다. 읽기셋·mcp__jarvis__는 평소대로.
3. **화면 제어**: 원격 턴은 `_pipeline_text`를 거치지 않으므로 모드 토글
   불가(토글은 음성 전용). CONTROL_GATE가 음성으로 켜진 채면 5분 만료가
   위험을 한정한다.
- 추가: remote_mode 동안 들어온 confirm성 도구는 전부 deny이므로
  "원격으로 rm 실행" 류는 구조적으로 불가능.

### 설정 (config M7 블록)
- `remote_enabled: bool = True`
- `remote_host: str = "0.0.0.0"` (LAN 수신; 테스트는 127.0.0.1)
- `remote_port: int = 8790`

### `docs/REMOTE.md` — 아이폰 단축어 설정 가이드
단축어 앱 → 새 단축어 "자비스": ①"입력 요청"(받아쓰기) ②"URL 내용 가져오기"
(POST, JSON {"text": 입력}, 헤더 Authorization: Bearer <토큰>) ③"결과 보기"
또는 "텍스트 말하기"(reply). 맥 IP 고정/Tailscale 주소 안내, Siri로
"자비스 실행해" 호출 안내.

## 에러 처리
- 서버 시작 실패(포트 사용 중 등) → 부팅 계속, "[원격] 시작 실패" 안내.
- 두뇌 예외 → 500 안내 JSON, 오케스트레이터는 finally로 IDLE 복귀.
- 인증 실패는 로그 1줄(스팸 방지 위해 내용 미기록), 응답 401.
- remote_turn 중 바지인(PTT)? — state가 THINKING이라 웨이크는 차단되지만
  PTT는 가능. PTT가 _cancel_pipeline해도 remote_turn은 _task가 아니므로
  취소되지 않는다 — 두 턴이 두뇌를 동시에 쓸 수 있는 잔여 레이스.
  v1 완화: remote_turn 동안 `self._remote_busy=True`로 표시하고
  `_on_release`의 파이프라인 시작과 `_on_wake_utterance`가 이를 확인해
  무시(짧은 안내 없이 폐기 — 원격 턴은 보통 수 초).

## 테스트 (실 SDK·네트워크 외부 노출 없음)
- RemoteServer: 127.0.0.1 임시 포트로 실제 기동 + urllib 호출 —
  토큰 OK/거부(401)/빈 text(400)/핸들러 예외(500)/404. 가짜 handler.
- token: 생성·재사용·0600 권한.
- remote_turn: 가짜 두뇌 — IDLE에서 응답 수집·한국어 reply·IDLE 복귀,
  busy면 거부 메시지, 예외에도 IDLE 복귀, remote_mode set/clear,
  PTT/웨이크 차단 플래그.
- _can_use_tool: remote_mode=True면 Bash가 confirm 없이 Deny(가짜 confirm
  호출 기록 0회), 읽기셋·jarvis 도구는 영향 없음.
- 배선: __main__ 가동 시 RemoteServer 시작(가짜로 기록).
- 라이브: 같은 와이파이 아이폰 단축어로 "지금 몇 시야?" 왕복.
