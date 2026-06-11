# 설계: 첫 실행 설정 UI (프로바이더 선택 + 로그인/키)

날짜: 2026-06-12
상태: 사용자 승인됨(순차 진행)
선행: 두뇌 추상화 + Gemini + GPT 어댑터(3 프로바이더 선택 가능)

## 목표

배포된 앱을 처음 켜면 **설정 UI**가 떠서 두뇌를 고른다(Claude / Gemini / GPT).
- Claude: 구독 로그인(번들 `claude` CLI OAuth). 키 불필요.
- Gemini: Google AI Studio API 키 붙여넣기.
- GPT: OpenAI API 키 붙여넣기.
선택+검증 성공 시 영구 저장(선택→파일, 키→keyring)하고 자비스를 띄운다. 다음
실행부터는 설정을 건너뛴다. 스카우트 권고대로 **stdlib HTTP + 브라우저 로컬
페이지**(orb_server 패턴 재사용) — 크로스플랫폼, 의존성 0.

## 컴포넌트

### 1) 영구 저장 — `jarvis/setup/store.py`
- 설정 파일 `~/.jarvis/setup.json`: `{"brain_provider": "...", "configured": true}`.
- `load_setup() -> dict`(없으면 {}), `save_setup(provider)`(원자 write, configured=true).
- 키는 keyring(service "jarvis"): gemini→user "gemini_api_key", gpt→"openai_api_key".
  `save_key(provider, key)`, `get_key(provider)->str|None`.
- `is_configured() -> bool`: setup.json의 configured=true이고 선택 프로바이더의
  자격이 갖춰짐(claude=항상 OK[구독은 CLI가 관리], gemini/gpt=keyring에 키 존재).
- `configured_provider() -> str|None`.

### 2) Settings가 저장된 선택을 읽게
- `Settings`에 `setup.json`을 소스로 추가: pydantic-settings의 `json_file`
  (`SettingsConfigDict(json_file=str(Path.home()/".jarvis"/"setup.json"))`). 이러면
  저장된 `brain_provider`가 기본값을 덮어쓴다(env가 최우선 유지). 충돌 없으면 이
  방식, 안 되면 `__main__`이 load_setup()으로 `brain_provider`를 주입.

### 3) 키 검증 — `jarvis/setup/validate.py`
- `async validate(provider, key, *, clients=None) -> tuple[bool, str]`:
  - gemini: 작은 genai 호출(`client.aio.models.generate_content(model, "hi")`) 성공?
  - gpt: 작은 openai 호출(`client.chat.completions.create(model, [{user:"hi"}])`) 성공?
  - claude: 키 없음 — 구독 로그인 여부를 가볍게 확인(번들 claude CLI 존재/로그인;
    v1은 "claude" 선택 시 항상 OK로 두고 실패는 첫 대화에서 안내).
  - 실패 시 한국어 사유("키가 올바르지 않습니다" 등). 클라이언트 주입 가능(테스트).

### 4) 설정 서버 — `jarvis/setup/server.py` + `setup.html`
- stdlib ThreadingHTTPServer(orb_server 패턴). `GET /` → setup.html(인라인 또는
  파일). `POST /setup` JSON `{provider, key?}` → validate → 성공 시 save_setup +
  save_key → `{"ok":true}` 반환 + 완료 이벤트 set. 실패 → `{"ok":false,"error":...}`.
- 로컬 전용 바인드(127.0.0.1, 임의 포트). 완료를 launcher가 기다릴
  `threading.Event`. 핸들러 주입형 validate(테스트).
- setup.html: 세 카드(Claude/Gemini/GPT) 라디오 + (gemini/gpt 선택 시) 키 입력칸 +
  "시작" 버튼. fetch로 POST, 성공 시 "설정 완료, 자비스를 시작합니다" 표시.
  영화풍 다크 테마(orb.html 톤). 순수 HTML/JS, 외부 의존 0.

### 5) 런처 — `jarvis/setup/launcher.py`
- `run_first_run_setup() -> str`: 서버 시작 → 기본 브라우저로 URL 열기
  (`webbrowser.open`) → 완료 Event 대기(타임아웃 없음; 사용자가 닫으면 종료) →
  서버 정지 → 선택된 provider 반환.

### 6) 부팅 배선 — `__main__.py`
- 진입 직후: `if not is_configured(): run_first_run_setup()` → 그 후 `Settings()`
  재로드(저장된 brain_provider 반영) → 평소 부팅. 이미 설정됨이면 바로 부팅.
- 콘솔에도 안내: 설정 UI가 브라우저에서 열렸음.

## 에러 처리
- 키 검증 네트워크 실패 → 페이지에 사유 표시, 재시도 가능(저장 안 함).
- setup.json 읽기/쓰기 실패 → 기본값(claude)로 진행, 콘솔 경고.
- 브라우저 자동 열기 실패 → 콘솔에 URL 출력(수동 접속).

## 테스트
- store: save/load 왕복, is_configured(claude=키 없이 OK, gemini=키 있어야),
  configured_provider, keyring 격리(테스트는 keyring 가짜/monkeypatch 또는 임시
  경로). setup.json은 tmp 경로 주입.
- validate: 가짜 클라이언트 — 성공/실패, 프로바이더별 호출 형태.
- server: 127.0.0.1:0 실서버 + urllib — GET / 200(html), POST /setup 성공 시
  save 호출+ok, 실패 시 ok=false, 잘못된 provider 거부. validate 주입.
- launcher: 가짜 서버/이벤트로 완료 반환(브라우저 열기 monkeypatch).
- 배선: is_configured False면 __main__이 setup 호출(가짜).
- 라이브(수동): 첫 실행 → 브라우저 설정 → Gemini 키 입력 → 자비스 기동.

## 비범위
- 설정 변경 UI(프로바이더 재선택)는 setup.json 삭제 후 재실행으로 갈음(v1).
- 패키징/서명(다음 sub-project).
