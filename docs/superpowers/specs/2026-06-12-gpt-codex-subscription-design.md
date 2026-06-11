# 설계: GPT 구독 연동 (Codex 토큰 — 유료 키 없이)

날짜: 2026-06-12
상태: 사용자 승인됨("codex 사용 중 아님 — 지금 테스트는 못 하지만 가능하게 만들어")
전제: 사용자는 ChatGPT Plus/Pro **구독자**. Claude처럼 로그인으로 GPT 사용.

## 핵심 사실 (웹 확인)

- `codex login`(OAuth)이 `~/.codex/auth.json`에 토큰 저장:
  `{"type":"oauth", "access_token":..., "refresh_token":..., "expires":<ms>,
   "accountId":<ChatGPT account id>}` (구현체별로 `tokens.{...}` 중첩 가능 — 양쪽 처리).
- 엔드포인트: `https://chatgpt.com/backend-api/codex/responses` — **Responses API** 사용.
  헤더: `Authorization: Bearer <access_token>`, `ChatGPT-Account-Id: <accountId>`.
  구독 크레딧으로 처리(토큰당 과금 아님), 5시간 롤링 제한.
- 만료 시 갱신: `POST https://auth.openai.com/oauth/token`,
  `{grant_type:"refresh_token", refresh_token, client_id:"app_EMoamEEZ73f0CkXaXp7hrann"}`.
- openai SDK가 Responses API를 공식 지원하므로 `AsyncOpenAI(base_url=Codex,
  api_key=access_token, default_headers={"ChatGPT-Account-Id": accountId})` +
  `client.responses.create(...)`로 호출. **base_url만 비공식**, 나머진 공식 스키마.

⚠️ 비공식 엔드포인트 — 예고 없이 바뀔 수 있음. 본인 구독 개인 사용은 용인되는
회색지대. 코드에 명시. 토큰은 비밀번호처럼 취급(로그 금지).

## 컴포넌트

### 1) `jarvis/brain/codex_auth.py` (자가완결·테스트 가능)
- `CODEX_AUTH_PATH = ~/.codex/auth.json`.
- `load_codex_auth(path=None) -> dict|None`: JSON 읽기. `access_token`/`refresh_token`/
  `expires`/`accountId`를 최상위 또는 `tokens.` 중첩 양쪽에서 추출. 없으면 None.
- `is_codex_logged_in(path=None) -> bool`.
- `_account_id_from(auth) -> str`: auth의 accountId, 없으면 access_token(JWT) 페이로드
  base64 디코드에서 `https://api.openai.com/auth`→`chatgpt_account_id` 추출(서명검증
  불필요).
- `async get_access(path=None, now_ms=None, http=None) -> tuple[str,str]`:
  load → 만료(expires < now_ms - 60s 여유)면 refresh(POST oauth/token, http 주입형
  httpx.AsyncClient) → 새 토큰 파일에 원자 저장 → (access_token, account_id) 반환.
  로그인 안 됐으면 RuntimeError("codex login이 필요합니다(`codex login`).").
  http·now_ms 주입으로 네트워크 없이 단위테스트.

### 2) GPTBrain 구독 모드 — `jarvis/brain/openai_brain.py`
- config: `gpt_auth: str = "subscription"`("subscription"|"api_key"),
  `gpt_subscription_base_url: str = "https://chatgpt.com/backend-api/codex"`,
  `gpt_subscription_model: str = "gpt-5.5"`(구독 기본; 미지원 시 폴백은 런타임 안내).
- `__init__`에 모드 분기. 실 클라이언트 생성:
  - api_key 모드(기존): `AsyncOpenAI(api_key=<keyring>)`, chat.completions 루프(그대로).
  - subscription 모드: `(token, acct) = await get_access()` →
    `AsyncOpenAI(base_url=gpt_subscription_base_url, api_key=token,
    default_headers={"ChatGPT-Account-Id": acct})` → **Responses API 루프**.
  - 클라이언트 주입(테스트)이면 모드와 무관하게 그 클라이언트 사용.
- **Responses API 루프** `_run_responses(user_payload)`:
  - `resp = await client.responses.create(model=self._sub_model,
    instructions=self._system_prompt(), input=input_items, tools=RESP_TOOLS,
    tool_choice="auto")`.
  - RESP_TOOLS: `[{"type":"function","name":t.name,"description":t.description,
    "parameters":t.parameters}]`(Responses는 평면 function).
  - 응답 파싱(덕타이핑, 가짜 가능): `resp.output`(list). function call 항목 =
    `type=="function_call"` with `.name`/`.arguments`(json str)/`.call_id`. 텍스트 =
    `type=="message"`의 content output_text 또는 `resp.output_text`.
  - 게이트: 각 function call마다 `tool_policy.decide(...)` → 허용 시 registry call,
    거부 시 사유. function call 항목들 + `{type:"function_call_output",
    call_id, output: result}`를 input에 append 후 재호출(최대 8회).
  - 최종 텍스트 → `split_ko` → 영어 yield + last_subtitle + history.add.
- respond()는 모드에 따라 `_run_chat`(기존) 또는 `_run_responses` 호출. 둘 다
  tool_policy 게이트·[KO]·history·memory 동일.
- translate(): subscription 모드면 `responses.create(instructions="Translate...",
  input=text)` 텍스트만; api_key 모드면 기존.

### 3) 설정 UI·저장 변경 (GPT = 구독 로그인)
- setup 카드 GPT: "ChatGPT 구독 로그인 (codex)" — 키 입력칸 없음. 대신 안내:
  "터미널에서 `codex login` 후 선택하세요." 무료/유료 배지 → "구독".
- store.is_configured: gpt → `codex_auth.is_codex_logged_in()`(키 대신 로그인 확인).
- validate: provider=="gpt" → codex 로그인됐으면 (True,"ChatGPT 구독 확인됨"),
  아니면 (False,"먼저 `codex login` 하세요").
- config 기본 `gpt_auth="subscription"`. (유료 키를 원하면 JARVIS_GPT_AUTH=api_key.)

## 테스트 (네트워크·실API 없음)
- codex_auth: 파일 파싱(평면/중첩), 만료 판정, refresh(가짜 http가 새 토큰 반환→
  파일 갱신), 미로그인 RuntimeError, account_id JWT 디코드, 원자 저장. tmp 경로.
- GPTBrain subscription: 가짜 client(`responses.create` 스크립트) — function_call→
  게이트→registry→function_call_output 회신→최종 [KO] 분리; 발송 거부; remote 차단;
  translate. api_key 모드 회귀(기존 chat 테스트 유지).
- store/validate: gpt가 codex 로그인 여부로 configured/validate(가짜 is_logged_in).
- 라이브(사용자, codex login 후): 실제 구독으로 한 턴.

## 비범위
- 토큰 풀링/다계정(ToS 명백 위반) — 금지.
- 패키징(다음).
