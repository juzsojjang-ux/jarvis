# 설계: Gemini 두뇌 어댑터

날짜: 2026-06-12
상태: 사용자 승인됨(순차 진행)
선행: 두뇌 추상화(Brain 프로토콜·split_ko·factory 디스패치)
공유 산출물: 이 sub-project가 만드는 **중립 도구 레지스트리**·**도구 권한 정책**을
다음 GPT 어댑터가 재사용한다(중복 0).

## 목표

`brain_provider="gemini"`면 GeminiBrain이 두뇌가 된다. Claude와 동일한 사용자
경험: 한두 문장 영어 발화 + `[KO]` 한국어 자막, 위트, jarvis 도구 30종 실행
(시간·날씨·앱·음악·타이머·메시지/메일 읽기·발송 등), 통역. **차이(정직)**: Gemini
SDK엔 Claude Code의 내장 Bash/파일 도구가 없으므로, 임의 셸·파일 작업은 v1
비범위 — Gemini 자비스는 jarvis 도구로 할 수 있는 일을 한다.

## 컴포넌트

### 1) 중립 도구 레지스트리 — `jarvis/tools/registry.py`
- `neutral_tools(memory=None) -> list[NeutralTool]`. `build_jarvis_mcp_server`가
  쓰는 것과 **같은 도구 객체 리스트**(SdkMcpTool: `.name/.description/
  .input_schema/.handler`)를 한 곳에서 만들고, 거기서 중립 스펙을 뽑는다.
  jarvis_mcp의 도구 리스트 구성을 `_build_tool_objects(memory)` 헬퍼로 추출해
  MCP 서버와 레지스트리가 공유(정의 중복 방지).
- `NeutralTool`(dataclass): `name`, `description`, `parameters`(JSON schema =
  input_schema), `async call(args: dict) -> str`. `call`은 핸들러를 호출하고
  `{"content":[{"type":"text","text":...}]}`에서 텍스트만 뽑아 반환(이미 한국어
  안내 문자열). 핸들러 예외는 잡아 "도구 실행 실패" 문자열(절대 raise 안 함).

### 2) 도구 권한 정책 — `jarvis/brain/tool_policy.py`
Claude 게이트(`subscription.py._can_use_tool`)는 claude 네임스페이스(mcp__jarvis__,
Bash, Read)용이라 건드리지 않는다. Gemini/GPT는 **민짜 도구 이름**만 다루므로
공유 정책 함수를 새로 둔다:
- `READONLY = frozenset({...})` — 읽기·무해(get_time/get_weather/battery_status/
  get_reminders/get_calendar_events/list_timers/get_messages/get_unread_mail/
  clipboard_read/capture_screen). (= 원격 허용목록과 동일.)
- `GUARDED = frozenset({"send_message","send_mail"})` — 발송, 확인 필요.
- `async def decide(name, *, remote_mode, trust_on, confirm) -> tuple[bool, str|None]`:
  - remote_mode면 READONLY만 허용, 그 외 (False, "원격에서는 실행할 수 없습니다").
  - trust_on이면 (True, None) — 전권.
  - name in GUARDED → confirm 있으면 confirm 결과, 없으면 (False, 거부 안내).
  - 그 외(일반 액션) → (True, None) 자동 허용(로컬, 사용자 현장).
  반환: (실행해도 되는가, 거부 시 두뇌에 돌려줄 한국어 사유).
- confirm 프롬프트는 발송 내용 표시(subscription `_confirm_prompt`와 같은 문구
  헬퍼를 `tool_policy`로 옮겨 공유하거나 간단 재작성).

### 3) GeminiBrain — `jarvis/brain/gemini.py`
`google-genai`(google.genai) 사용. Brain 프로토콜 구현. 주입 가능
(`client_factory` 기본 실제 SDK; 테스트는 가짜).
- `__init__(settings, memory, persona_text, *, confirm=None, client_factory=None)`:
  `last_subtitle=""`, `remote_mode=False`, 도구 레지스트리·정책 준비. 모델
  `settings.gemini_model`(기본 "gemini-2.5-flash"). API 키는 keyring(아래 설정).
- 시스템 프롬프트: 기존 `_guidance_for("en")` + persona + `[KO]` 규약(영어로
  말한 뒤 새 줄에 `[KO] 한국어`). 도구 사용 지침 동일.
- `async respond(user_text)`: google-genai **함수호출 루프** — 모델이 function
  call을 내면 정책 `decide`로 게이트 → 허용 시 레지스트리 `call` 실행 후 결과를
  function response로 회신 → 모델이 최종 답 생성. 최종 텍스트를 `split_ko`로
  분리해 영어는 yield, 한국어는 `last_subtitle`. 스트리밍 가능하면 부분 발화.
  max 도구 반복 8회(무한루프 방지). 거부된 도구는 사유를 function response로
  돌려 모델이 사용자에게 설명하게.
- `async translate(text, target_lang)`: 도구 없는 1회 호출(시스템 "Translate to
  {target}. Output only translation."). 영속 클라이언트 재사용 가능.
- `warm()`/`warm_interpret()`: best-effort 짧은 호출. `close()`: 정리.

### 4) 설정·팩토리·키
- config: `gemini_model: str = "gemini-2.5-flash"`. API 키는 keyring
  서비스 `"jarvis"`, 사용자 `"gemini_api_key"`(첫 실행 UI가 저장; 여기선 읽기
  헬퍼만). 키 없으면 GeminiBrain 생성 시 명확한 안내 예외.
- factory: 두뇌추상화에서 둔 `NotImplementedError` 자리를 `from .gemini import
  GeminiBrain; return GeminiBrain(...)`로 교체.

### 5) 의존성
`pip install google-genai` (.venv). pyproject에 `gemini` extra로 기록.

## 에러 처리
- 도구 핸들러·정책·번역 실패는 한 턴을 깨지 않는다(안내 문자열/IDLE).
- API 키 부재·인증 실패 → 한국어 안내(자비스가 말로 알림).
- 함수호출 루프 8회 초과 → 현재까지로 마무리.

## 테스트 (가짜 genai 클라이언트, 실제 API 미호출)
- `neutral_tools`: 30개, 각 name/parameters 존재, `call`이 핸들러 텍스트 반환,
  핸들러 예외 시 안내.
- `tool_policy.decide`: remote→readonly만, trust→전권, guarded→confirm 분기,
  일반→자동. confirm 호출/미호출 검증.
- GeminiBrain(가짜 client): function call → 정책 게이트 → 레지스트리 실행 →
  최종 답 `[KO]` 분리(영어 yield/한국어 last_subtitle); 발송 도구는 confirm
  없으면 거부 사유 회신; remote_mode면 액션 도구 거부; translate 경로.
- factory: provider="gemini" → GeminiBrain(가짜 키).
- 프로토콜: `isinstance(GeminiBrain(...), Brain)`.

## 비범위
- 임의 Bash/파일(Gemini SDK 내장 없음) — v1 제외.
- 실제 키 라이브 테스트 — 첫 실행 UI에서 키 입력 후.
