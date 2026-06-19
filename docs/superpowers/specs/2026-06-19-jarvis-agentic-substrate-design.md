# JARVIS v3.1 — 에이전트 토대(Agentic Substrate) 설계

- 작성일: 2026-06-19
- 상태: 설계 승인 대기(브레인스토밍 산출물)
- 범위: **Phase A — 안전·확장 토대.** 확장 로드맵 A→H 중 첫 사이클.
- 선행 정찰: `jarvis-brain-upgrade-scout`, `jarvis-upgrade-ideation` 워크플로(코드베이스 매핑 + SDK 사실 확인 + 발산 브레인스토밍).

---

## 0. 북극성(North Star) — 채택된 전체 비전

자비스 기본 두뇌는 **이미** Claude Agent SDK(`claude-agent-sdk==0.2.94`, Claude Code 엔진 번들, 구독 로그인)
기반이고 MCP가 이미 주력 도구 메커니즘이다. 따라서 이번 대규모 업데이트는 "두뇌 교체"가 아니라
**SDK의 안 쓰던 강력한 표면(hooks·plugins·subagents·memory)을 켜고, 가짜 키워드 라우팅을 진짜 지능으로
바꾸는 것**이다.

핵심 명제(여러 차원 상승의 정체): **싸고·연속적이고·온디바이스인 층을 드물고·유료고·심층인 두뇌에서 분리**
하고, 그 한 수를 세 곳(연산=반사뇌 / 지각=무료 OCR 데몬 / 기억=World Model 그래프)에 적용한다.
구독-로그인 과금이 두 번째 승수다 — speculation·연속 자가검증·야간 자가개선이 사실상 공짜다.
단, **데일리 드라이버 신뢰성이 신성**하므로 영리한 기능은 신뢰성 스파인을 깐 뒤에 올린다.

### 채택 로드맵(요약, 본 스펙은 A만 구현)
- **A — 토대(본 스펙):** Hooks 가드레일 · 플러그인 패스스루 · 권한 자가복구 (+ 가벼운 도구 정책 맵)
- **B — 신뢰성·무음 스파인:** 지연 워치독 + 진짜 취소(`client.query()` 중단, 알려진 버그 수정) · 블랙박스
  플라이트 레코더 · 서킷 브레이커 · 즉답 오프너 · 서버사이드 인터럽트
- **C — 두 개의 뇌:** 온디바이스 반사뇌(System-1) · 부분 STT 추측 생성 · 선행 프리페치
- **D — 메모리 대사:** World Model 그래프 · 야간 '꿈' 정리/망각 · 선호 원장 · '이어가기' · 메모리 방화벽
- **E — 늘 보고 있음:** Ambient Perception 데몬(`now.json`) · 막힘 감지 · 눈 해설 · (후) 음향/카메라
- **F — 스스로 안전하게 행동:** 음성 규칙 엔진 · 센티넬 + 되돌림 저널 · 감사형 추론 · council 투표 게이트
- **G — 맥 너머:** 듀플렉스 폰 채널 · 출력 라우터 · MCP 음성설치 마켓 · 브라우저 컴패니언 · 비서 · 맥+윈도 스웜
- **H — 자가개선·와일드:** 스킬 TDD 게이트 · 평가기반 A/B 자가개선 · 디지털 트윈 · 텔레포니 · 비전 오퍼레이터 · 비주얼 '리와인드'

> B 이후는 별도 스펙→플랜→구현 사이클. 각 phase는 독립적으로 출시 가능하고 다음 phase의 위험을 줄이도록 정렬됨.

> **초기 11개 후보의 행방(흡수·날카로워짐, 누락 아님):** 스트리밍 진행이벤트→**B**(무음 스파인), 적응형 라우팅→**C**(반사뇌가 상위호환),
> 의미기반 메모리v1→**D**(World Model 그래프/대사작용이 상위호환), 풍부한 MCP(파일/캘린더/Gmail)→**G**(음성설치 마켓), 서브에이전트(`agents=`)·통합
> 도구 레지스트리는 **D·F·G가 소비하는 교차 프리미티브**라 해당 phase에서 도입. Phase A는 이들을 일부러 빼고 **게이트·플러그인·권한**만 좁게 잡는다(토대부터).

---

## 1. 이번 스펙 범위(Phase A)

### 포함
1. **Hooks 가드레일** — 모든 도구 호출을 `PreToolUse` 훅으로 **무조건** 게이트. 현재 `allowed_tools`가
   `can_use_tool`을 우회하는 구멍을 봉쇄하고, 원격 차단·발송 확인·전권(TRUST_GATE) 게이트를 훅으로 재표현.
2. **도구 정책 맵** — 도구명을 신뢰 등급으로 분류하는 가벼운 단일 모듈(전체 크로스-프로바이더 스키마 통합 아님).
3. **Plugins 패스스루** — `ClaudeAgentOptions.plugins=[{"type":"local","path"}]` 배선 + 플러그인별 신뢰 모델
   (제3자=기본 비신뢰) + 설정 토글.
4. **권한 자가복구** — 시작 시 OS(TCC) 권한 프리플라이트 점검 + 도구가 권한으로 막힐 때 그 순간 설정 열고 재요청.

### 의도적 제외(YAGNI → 후속 phase)
- **통합 도구 레지스트리(4두뇌 공통 스키마 생성):** 키워드→도구호출 마이그레이션이 실제로 필요로 하는 것 → Phase B/그 이후.
  본 스펙은 훅이 쓸 **분류용 정책 맵**만 둔다.
- 스트리밍 도구-진행 이벤트, 반사뇌, 메모리 대사, 지각 데몬 등 → 로드맵 B~H.
- 마켓플레이스 **자동 다운로드/설치**: SDK가 `type:"local"`만 지원 → 본 스펙은 "사용자가 폴더에 둔 로컬 플러그인 로드"만.

---

## 2. 확정된 설계 결정(브레인스토밍 합의)

| 결정 | 선택 | 함의 |
|---|---|---|
| 라운드 범위/순서 | **토대부터 순차** | A를 작고 저위험으로, B에서 능력 점프 |
| 권한 자가복구 강도 | **프리플라이트 + 막힐 때 재요청** | 시작 시 일괄 점검, 평상시 조용, 막히면 그 순간 재요청. 능동 반복 알림 없음 |
| Hooks 기본 보안 수위 | **더 느슨** | 로컬 세션은 대부분 자동허용, 외부 발송·삭제만 확인 |
| 파국적 데니리스트 | **유지(비양보)** | 느슨함은 "확인 마찰" 감소이지 음성 인젝션 노출이 아님 |
| 플러그인 신뢰 | **제3자=기본 비신뢰** | 추가한 플러그인만 로드 + 그 도구는 자동허용 제외, 플러그인별 신뢰 토글로 승격 |

---

## 3. 아키텍처 & 컴포넌트

격리 원칙: 새 로직은 신규 모듈로 빼고, `subscription.py`는 **배선만** 바꾼다(거대 파일 비대화 방지).

### 신규 모듈
| 파일 | 책임 | 핵심 인터페이스 |
|---|---|---|
| `jarvis/brain/gating.py` | 게이트 단일 권위. `PreToolUse` 콜백과 `hooks=` dict 구성 | `build_hooks(brain) -> dict[HookEvent, list[HookMatcher]]` |
| `jarvis/tools/policy.py` | 도구명 → 신뢰 등급 분류 + 파국적 데니리스트 | `classify(tool_name, tool_input, *, plugin_trust) -> Tier`, `is_catastrophic(tool_name, tool_input) -> bool` |
| `jarvis/tools/plugins.py` | 로컬 플러그인 발견 + 신뢰 레지스트리 | `discover() -> list[SdkPluginConfig]`, `trusted_servers() -> set[str]`, `plugin_servers() -> set[str]` |
| `jarvis/system/permissions.py` | OS 권한 프리플라이트 + 막힐 때 안내(mac/win) | `preflight() -> list[PermIssue]`, `request(capability)`, `classify_failure(exc|text) -> capability|None` |

### 수정
| 파일 | 변경 |
|---|---|
| `jarvis/brain/subscription.py` | `_options()`에 `hooks=build_hooks(self)` + `plugins=plugins.discover()` 추가. `can_use_tool=` **제거**(→훅). `_can_use_tool`/`_confirm_prompt` 로직은 `gating.py`로 이전(brain은 `_confirm`·`remote_mode`만 노출). |
| `jarvis/core/config.py` | `plugins_enabled: bool=False`, `permission_preflight: bool=True`, (선택) `bash_auto_allow: bool=True` 등 토글 |
| `jarvis/__main__.py`(또는 부팅 경로) | 시작 시 `permissions.preflight()` 호출 → 이슈 있으면 HUD/음성 1회 안내 |
| `jarvis/setup/server.py`·`store.py` | 설정창에 플러그인 on/off · 신뢰 토글 노출(기존 토글 패턴 따름) |

### 외부 사실(검증 완료, `claude_agent_sdk/types.py`)
- `ClaudeAgentOptions.hooks: dict[HookEvent, list[HookMatcher]] | None`
- `HookEvent` ⊇ `"PreToolUse" | "PostToolUse" | "PostToolUseFailure" | "PermissionRequest" | ...`
- `HookMatcher(matcher: str|None, hooks: list[HookCallback], timeout: float|None)` — `matcher`는 `"Bash"` /
  `"Write|Edit"` 같은 도구명 패턴, `None`이면 전체 매칭(가정 — TDD로 확인).
- `HookCallback = async (input: HookInput, tool_use_id: str|None, context: HookContext) -> HookJSONOutput`
- `PreToolUse` 차단: 반환 `{"hookSpecificOutput": {"hookEventName":"PreToolUse",
  "permissionDecision": "deny"|"allow"|"ask", "permissionDecisionReason": str}}`
- `ClaudeAgentOptions.plugins: list[SdkPluginConfig]`, `SdkPluginConfig = {"type":"local", "path": str}`
- `ClaudeAgentOptions.agents: dict[str, AgentDefinition]`(Phase 후속), `get_mcp_status/reconnect_mcp_server`, Sandbox config 존재.
- 보조: `claude_agent_sdk/testing` 하네스로 훅을 결정적으로 테스트 가능.

---

## 4. Hooks 가드레일(핵심) — 판정 흐름

`build_hooks(brain)`는 `{"PreToolUse": [HookMatcher(matcher=None, hooks=[pre_tool_use])]}`를 반환한다.
`pre_tool_use(input, tool_use_id, ctx)`는 `input["tool_name"]`/`input["tool_input"]`로 아래 순서를 평가한다(먼저 매칭되는 것이 이김):

1. **원격(아이폰) 턴** — `brain.remote_mode`가 켜져 있으면: `policy`의 원격 읽기전용 허용목록(`_REMOTE_SAFE_JARVIS`
   + `_SAFE_TOOLS`)만 `allow`, 나머지 `deny`. *(현 `_can_use_tool` 동작 그대로 보존 — 최우선)*
2. **파국적 데니리스트** — `policy.is_catastrophic(...)`이면 무조건 `deny`. 음성 인젝션 최후 방어선:
   - `Bash` 명령이 `rm -rf /`·`rm -rf ~`·`:(){ :|:& };:`·`mkfs`·`dd of=/dev/`·`> /dev/sda`·`curl … | sh` 등 파괴 패턴
   - 자격증명/키 경로 read/write: `~/.ssh`, `~/.aws`, `~/.config/gh`, 키체인, `*.pem`, `id_rsa`, `.env`(민감)
   - (목록은 `policy.py` 상수로, 확장 가능)
3. **전권(TRUST_GATE) on** — `TRUST_GATE.is_on()`이면 (1·2 통과분에 한해) `allow`. *(현 동작 보존)*
4. **"느슨" 기본 정책** — `policy.classify(...)` 등급별:

| 등급 | 예시 | 판정 |
|---|---|---|
| `READ` | `Read`/`Grep`/`WebSearch`/`WebFetch`/`TodoWrite`/`NotebookRead`, jarvis 조회 도구(get_time·weather·battery·capture_screen·recall_memory 등) | **자동 허용** |
| `LOCAL_REVERSIBLE` | 앱 실행·볼륨·음악·타이머·`screen_control`·`click_by_name`·`show_panel`, 범위 내 `Write`/`Edit`, 비파괴 `Bash` | **자동 허용**(느슨) |
| `SEND` | `send_message`·`send_mail` | **음성 확인** |
| `DELETE` | 기존 파일 삭제/덮어쓰기, 파괴적 `Bash`(rm·mv 덮어쓰기·kill -9·shutdown) | **음성 확인** |
| `PLUGIN_UNTRUSTED` | 신뢰 안 한 플러그인이 가져온 도구 중 비-READ | **음성 확인** |
| `EXTERNAL_MCP` | `mcp.json`의 외부 서버(premiere 등) 비-READ | **음성 확인**(현 동작 유지) |

판정이 "음성 확인"이면 훅이 `await brain._confirm(prompt)`(기존 VoiceConfirm) 호출 → `allow`/`deny`.
`brain._confirm`이 없으면(헤드리스) `deny`. 확인 프롬프트 문구는 기존 `_confirm_prompt` 규칙 이전.

> **Bash 범위/덮어쓰기 정의**
> - "범위 내" = `$HOME`, 현재 작업 디렉터리 하위, `~/.jarvis` (단 §2 민감경로 제외). 그 밖(시스템 경로 등) Write/Edit는 `DELETE` 취급(확인).
> - 비파괴 `Bash` 판정은 보수적 패턴 매칭(파괴 동사 부재 + 데니리스트 미해당). 애매하면 `DELETE`로(확인). `config.bash_auto_allow=False`면 모든 Bash 확인으로 강제.

### 우회 구멍 봉쇄(핵심 메커니즘)
6개 읽기 빌트인(`WebSearch/WebFetch/Read/Glob/Grep/TodoWrite`)은 `allowed_tools`에 **남겨**(권한 프롬프트 생략)
두되, `PreToolUse` 훅은 이들에도 발화하므로 위험한 `Read`/`WebFetch`(예: 자격증명 경로·데니리스트)는 `deny`가 된다.
즉 게이트가 **무조건**이 된다. *(가정: PreToolUse 훅이 allowed_tools 자동승인보다 먼저 평가됨 — §9 검증 항목)*

---

## 5. Plugins 패스스루

- **발견:** `~/.jarvis/plugins/<name>/`의 각 디렉터리를 로컬 플러그인으로 보고
  `[{"type":"local","path": str(<name> dir)}]` 생성. `config.plugins_enabled`가 거짓이면 빈 목록(완전 비활성).
- **신뢰:** `~/.jarvis/plugins/trust.json` = `{ "<plugin-or-server-name>": true }`. 기본 부재 → 비신뢰.
  - `plugins.trusted_servers()` → 신뢰된 플러그인이 제공하는 MCP 서버명 집합.
  - `policy.classify`는 `mcp__<server>__*` 도구의 `<server>`가 플러그인 서버이고 비신뢰면 `PLUGIN_UNTRUSTED`로 분류
    → 비-READ 동작은 확인. 신뢰로 승격되면 `LOCAL_REVERSIBLE`/`READ`처럼 자동허용.
- **격리:** `setting_sources=[]`는 유지(호스트 Claude Code 설정/스킬/훅 유입 차단). 플러그인은 명시적으로 둔 것만.
- **범위 밖:** 마켓플레이스 자동설치·`reconnect_mcp_server` 라이브 부착(음성설치)은 Phase G.

---

## 6. 권한 자가복구(프리플라이트 + 막힐 때)

### 6.1 프리플라이트(시작 시 1회)
`permissions.preflight()`가 필요한 OS 권한 상태를 **조회**(추측 아님):
- **macOS(pyobjc):**
  - 손쉬운 사용(Accessibility): `AXIsProcessTrusted()`
  - 화면 기록(ScreenCapture): `CGPreflightScreenCaptureAccess()`
  - 마이크(Microphone): `AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio)`
  - 입력 모니터링(ListenEvent): `IOHIDCheckAccess(kIOHIDRequestTypeListenEvent)`
- **Windows:** 해당 모델 없음 → 빈 목록(no-op).

이슈가 있으면 부팅 직후 **HUD 패널 + 음성 1회** 안내("○○ 권한이 꺼져 있습니다. 켜주세요")하고 해당 설정 창을 연다
(`x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility` 등 딥링크, 또는
`AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})` / `CGRequestScreenCaptureAccess()`).
모두 켜져 있으면 조용. **반복 알림 없음**(결정사항).

### 6.2 막힐 때(런타임)
도구 실행이 OS 권한 거부로 실패하면 — 게이트는 허용했는데 OS가 막은 경우 —
`permissions.classify_failure(...)`가 실패를 권한 종류로 매핑하고 `permissions.request(capability)`가 그 순간
설정 창을 열며 "○○ 권한을 켜주세요"를 1회 재요청. 평상시 잔소리 없음.
- 매핑 예: `screen_control`/`capture_screen` 실패 → ScreenCapture·Accessibility; STT 무입력 → Microphone·ListenEvent.
- 훅이 `deny`한 경우(확인 거부·원격 차단)는 권한 문제가 아니므로 그대로 거부 메시지(자가복구 대상 아님).

---

## 7. 데이터 흐름(한 턴)

```
사용자 발화/타자
  → orchestrator(상태머신: 변경 없음)
  → SubscriptionBrain.respond()  →  client.query()  (도구 호출 발생 시)
        └─ 각 도구 호출마다 PreToolUse 훅:
             remote_mode? → 허용목록만
             catastrophic? → deny
             TRUST_GATE on? → allow
             classify → READ/LOCAL=allow | SEND/DELETE/PLUGIN_UNTRUSTED/EXTERNAL_MCP=confirm
        └─ 도구가 OS 권한으로 실패 → permissions.request(capability) (설정 열기+1회 재요청)
  → 스트리밍 [KO] 분리 → TTS (변경 없음)
시작 시(부팅): permissions.preflight() → 이슈 1회 안내
```

---

## 8. 회귀/호환성(가장 중요 — 데일리 드라이버 신성)

- **건드리지 않음:** 오케스트레이터 상태머신(IDLE/CAPTURING/TRANSCRIBING/THINKING/SPEAKING), PTT, wake word,
  바지인 취소, follow-up 윈도우, 원격(아이폰) 허용목록의 **의미**, 스트리밍 [KO] 분리, TTS/RVC.
- **행동 동등성 우선:** 훅은 먼저 기존 `_can_use_tool`의 정확한 동작(원격 차단·발송 확인·전권 게이트·jarvis 읽기
  자동허용)을 재현한 뒤, 그 위에 (a) 데니리스트 (b) 플러그인 비신뢰 (c) "느슨" 자동허용 확대 (d) 읽기 빌트인
  우회 봉쇄를 더한다.
- **느슨으로 인한 동작 변화(의도적):** 비파괴 `Bash`/범위 내 `Write`·`Edit`/화면제어가 (전권 아니어도) 자동허용으로
  바뀐다. `config.bash_auto_allow=False`로 Bash만 다시 깐깐하게 가능.
- **다른 두뇌(API-claude/gemini/gpt):** 본 스펙의 훅/플러그인은 SubscriptionBrain 한정. 타 브레인 경로는 변경 없음.

---

## 9. 미해결 가정 — 구현(TDD) 중 검증

1. **PreToolUse 훅이 `allowed_tools` 자동승인보다 먼저 평가되어 deny 가능한가.** — `claude_agent_sdk/testing`으로
   읽기 빌트인(예: 데니리스트 경로 `Read`)이 실제 차단되는지 확인. 거짓이면 폴백: 6개 읽기 빌트인을 `allowed_tools`
   에서 빼고 훅이 자동허용(콜백 1회 추가, 무해).
2. **`HookMatcher(matcher=None)`이 전체 도구를 매칭하는가.** — 거짓이면 도구별/광역 패턴(`"*"` 또는 알려진 도구명
   유니온)으로 대체.
3. **훅 콜백이 `await brain._confirm(...)`처럼 비동기 음성 확인을 수행하고 그동안 SDK가 대기하는가**(타임아웃
   `HookMatcher.timeout` 충분히 크게). — 확인 필요. 음성 확인이 타임아웃보다 길면 `deny` 폴백.
4. **pyobjc 권한 조회 API가 배포 `.app`(PyInstaller frozen)에서 동작하는가.** — 안 되면 베스트-에포트 프로브로 폴백,
   실패는 무해(프리플라이트는 best-effort).

---

## 10. 에러 처리

- 훅 내부 예외 → **안전측 폴백 = deny**(단, 그 때문에 무해 도구가 막히지 않게 READ/LOCAL은 예외를 삼키고 allow하되
  로깅). 게이트가 깨져 전부 막히는 것 vs 전부 열리는 것 사이에서 "민감군은 deny, 무해군은 allow" 보수 정책.
- `plugins.discover()`/`trust.json` 파싱 실패 → 빈 목록/비신뢰(플러그인 없음과 동일). 부팅을 막지 않음.
- `permissions.*` 실패(딥링크·pyobjc) → 조용히 best-effort. 턴을 깨지 않음.
- 모든 신규 모듈: 방어적(절대 raise로 음성 루프를 깨지 않음), stdlib/pyobjc 위주.

---

## 11. 테스트 전략(TDD)

각 기능은 실패 테스트 먼저 → 구현 → 통과.
- **`policy.py`(단위):** 등급 분류표 — 읽기/로컬/발송/삭제/플러그인/외부MCP 각 케이스, 데니리스트 적중(`rm -rf`,
  `~/.ssh` read 등), Bash 파괴/비파괴 경계, 범위 내/외 Write.
- **`gating.py`(단위, SDK testing 하네스):** 원격 차단 우선, 데니리스트 deny, 전권 allow, 느슨 자동허용, 발송 확인
  호출, 읽기 빌트인 우회 봉쇄(민감 Read deny), 확인 거부 시 deny, `_confirm` 없을 때 deny.
- **`plugins.py`(단위):** 발견/빈 목록(toggle off), trust.json 파싱·신뢰 승격이 분류에 반영, 깨진 json 안전.
- **`permissions.py`(단위, 모킹):** preflight가 꺼진 권한을 이슈로 보고, classify_failure 매핑, request가 딥링크
  호출(부수효과 모킹). Windows no-op.
- **통합:** 위험 도구 deny·읽기 허용·발송 확인이 한 턴에서 일관 동작. 기존 원격/발송 테스트 회귀 없음.

---

## 12. 산출물 / 사용설명서

- 코드: §3의 신규 4모듈 + `subscription.py`/`config.py`/setup 배선.
- **사용설명서(`docs/사용설명서.md`) 갱신**: 플러그인 추가 방법(`~/.jarvis/plugins/`), 신뢰 토글, 권한 자가복구 동작,
  "느슨" 보안 수위와 데니리스트 설명, `bash_auto_allow` 토글. (표준 운영 규칙: GitHub 반영 시 상세 변경설명 + 설명서 최신화)
- 버전: `pyproject.toml` 3.1.0 후보(릴리스는 별도 결정).

---

## 13. 다음 단계

본 스펙 승인 → `writing-plans` 스킬로 Phase A 구현 계획 작성 → `subagent-driven-development`(TDD)로 실행.
