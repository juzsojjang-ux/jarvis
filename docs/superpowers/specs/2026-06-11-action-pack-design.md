# 설계: 액션 팩 (3단계 능력 확장 — 3a)

날짜: 2026-06-11
상태: 사용자 승인됨
선행: 1단계 웨이크워드, 2단계 능동적 자비스 (가동 중)

## 3단계 전체 구도 (사용자 합의)

10개 능력을 3분할: **3a 액션 팩(이 문서)** → 3b 정보 팩(파일 찾기·읽기,
메시지·메일 읽기, 자동 기억, 통역 모드) → 3c 화면 인식(스크린샷→두뇌 비전,
기술 검증 분리). 제외 합의: 뉴스 브리핑, 프리미어 연동(추후), 사진/지도,
computer-use급 앱 조작(별도 대형 프로젝트).

## 목표 (3a)

음성으로 되는 일상 액션 5종: 타이머(완료 시 음성 알림), 시스템 토글,
클립보드 읽기/쓰기, macOS 단축어 실행, 음악 지정 재생. 전부 기존
jarvis_mcp 패턴(주입형 runner + @tool + JARVIS_TOOL_NAMES)으로.

## A. 타이머 — 능동 엔진 재활용

```
"5분 타이머" → 두뇌 set_timer 도구 → TimerBoard(공유 객체) 등록
TimerMonitor(interval 1s) → 만기 → Announcement("timer_done", prio 1)
→ 자비스 음성 알림 → follow-up 창
```

- `jarvis/proactive/timers.py`: `TimerBoard` — `add(label, seconds, clock) -> id`,
  `cancel(label_or_id) -> bool`, `listing() -> list[(label, 남은초)]`,
  `pop_due(now) -> list[label]`. 스레드 안전(락) — MCP 도구(비동기 루프)와
  모니터(to_thread) 양쪽에서 접근.
- `TimerMonitor(board)` (monitors.py): `interval_s = 1.0`, pop_due → kind
  `timer_done`, prompt `f"타이머 종료: {label}"`, prio 1, ttl 120(놓치면 2분
  내 전달, 그 후 폐기).
- MCP 도구: `set_timer(minutes?, seconds?, label?)` (없으면 label 자동
  "타이머"), `cancel_timer(label?)` (생략 시 1개면 그것, 여럿이면 목록 안내),
  `list_timers()`.
- 인프로세스 SDK MCP 서버이므로 TimerBoard 인스턴스를 배선(__main__)에서
  만들어 `build_jarvis_mcp_server(memory, timers=board)`와
  `build_monitors(settings, timers=board)` 양쪽에 주입.
- **엔진 변경 1건**: `ProactiveEngine(..., cooldown_overrides: dict[str, float]
  | None = None)` — `_pick`의 kind 쿨다운에서 override 우선. 배선에서
  `{"timer_done": 0.0}` 전달(연속 타이머 2개가 10분 쿨다운에 막히지 않게).

## B. 시스템 토글 — `system_toggle(target, state)`

| target | 구현 | 비고 |
|---|---|---|
| `dark_mode` | osascript appearance preferences (on/off/toggle) | |
| `wifi` | `networksetup -setairportpower <dev> on|off` | 장치명은 `networksetup -listallhardwareports`에서 Wi-Fi 포트를 찾아 결정(en0 하드코딩 금지), 1회 캐시 |
| `bluetooth` | `blueutil -p 1|0` | 미설치면 "brew install blueutil" 안내 답변 |
| `brightness_up/down` | osascript System Events key code 144/145 | 호출당 4회 키입력(약 25% 변화) |
| `display_off` | `pmset displaysleepnow` | 기존 lock_screen과 동일 명령 — 도구 설명으로 구분 |
| `sleep` | `pmset sleepnow` | 재시동/종료는 범위 제외 |

방해금지(DND)는 macOS가 안정적 CLI를 제공하지 않아 v1 제외 — 사용자가
단축어 앱에서 "방해금지" 단축어를 만들면 `run_shortcut`으로 즉시 가능
(이 우회를 도구 설명에 명시해 두뇌가 안내하게 한다).

## C. 클립보드 — `clipboard_read()` / `clipboard_write(text)`

- 읽기: `pbpaste` (최대 4000자로 자르고 "...이하 생략" — 두뇌 컨텍스트 보호).
  요약·낭독은 두뇌가 알아서.
- 쓰기: `pbcopy` (stdin으로 전달). "방금 말한 거 메모에 적어줘"는 기존
  create_note가 담당 — 클립보드 쓰기는 "복사해줘" 계열.

## D. 단축어 — `run_shortcut(name)` / `list_shortcuts()`

- `shortcuts run <name>` / `shortcuts list`. 실행 결과 stdout 있으면 요약해
  전달. 이름 불일치 시 목록에서 유사한 것 안내.
- 안전: 단축어는 사용자가 직접 만든 것뿐이고 음성으로 이름을 불러 실행 —
  추가 확인 없음. (단축어 실행이 만능 훅 — DND, 스마트홈 등 무한 확장.)
- timeout 30s (단축어는 길 수 있음 — 그 이상은 백그라운드로 돌고 있다고 답).

## E. 음악 지정 재생 — `play_music(query, kind="any")`

- kind: `track|artist|playlist|album|any`. osascript Music.app:
  track → `play (first track whose name contains q)`,
  artist → 해당 아티스트 곡 셔플, playlist/album → 해당 컬렉션 재생,
  any → track→artist→playlist 순 시도.
- 매칭 실패 시 "라이브러리에서 못 찾았습니다" (Apple Music 카탈로그 검색은
  범위 외 — 라이브러리 한정임을 도구 설명에 명시).

## 두뇌 지침

도구 설명만으로 충분 — 지침 변경 없음. (단, 도구 설명에 한계·우회를
명시해 두뇌가 자연스럽게 안내하도록 한다: blueutil, DND→단축어, 라이브러리 한정.)

## 설정

추가 없음 (타이머 ttl/쿨다운 예외는 코드 상수 — 노브 필요성이 입증되면 추가).

## 에러 처리

- 모든 runner 호출 timeout (osascript 10s, shortcuts 30s) + 실패 시 한국어
  안내 문자열 반환(도구는 절대 raise하지 않음 — 두뇌가 말로 전달).
- TimerBoard는 락으로 보호, 모니터 쪽 예외는 엔진 격리가 흡수(기존).

## F. 풀 Claude Code 능력 개방 (사용자 추가 요구: "이 능력들만 되게 설정하지 말고 클로드 코드로 할 수 있는 건 다 되게")

개별 도구 화이트리스트를 넘어, 두뇌가 Claude Code의 모든 도구(Bash, 파일
읽기/쓰기/수정, Glob/Grep 등)를 쓸 수 있게 한다. 안전장치는 **음성 확인
게이트**: claude-agent-sdk의 `can_use_tool` 권한 콜백(설치 버전 0.2.x에서
시그니처 확정: `async (tool_name, input, ToolPermissionContext) ->
PermissionResultAllow|Deny`)에 기존 `VoiceConfirm.confirm(prompt)->bool`을
연결한다.

- `_options()` 변경: `disallowed_tools` 제거, `allowed_tools`(자동 허용)=
  WebSearch/WebFetch/JARVIS_TOOL_NAMES/Read/Glob/Grep/TodoWrite,
  `can_use_tool=self._can_use_tool`, `cwd=str(Path.home())`,
  `max_turns` 20(장기 작업 헤드룸).
- `_can_use_tool`: 읽기 전용 안전셋(Read/Glob/Grep/TodoWrite/WebSearch/
  WebFetch)은 즉시 허용. 그 외(Bash/Write/Edit/NotebookEdit/기타)는 도구별
  요약(Bash→명령 80자, Write·Edit→파일 경로)을 음성으로 물어 "네"면 Allow,
  "아니/불명확/confirm 미주입"이면 Deny(차단이 기본 — 잘못 들은 음성이
  파괴 행위를 시키는 일은 없어야 한다).
- SubscriptionBrain이 confirm 콜백을 받도록 factory 경유 주입(현재 미주입).
- 지침 1문장: 전체 도구 사용 가능, 파괴적 단계는 음성 확인됨, 단순 동작은
  전용 jarvis 도구 우선(볼륨에 Bash osascript 쓰지 말 것).

## 테스트

- TimerBoard: add/cancel/listing/pop_due(가짜 시계, 중복 라벨, 만기 순서).
- TimerMonitor: 만기 시 1회 알림, ttl 120.
- 엔진: cooldown_overrides 동작(override 0이면 연속 전달).
- 도구 액션 함수: 전부 fake runner — 명령행 인자 검증 + 출력 파싱 +
  실패 메시지. blueutil 부재 분기.
- 배선: build_jarvis_mcp_server(timers=)·build_monitors(timers=) 주입,
  JARVIS_TOOL_NAMES 등록.
- 라이브: "5분... 아니 10초 타이머" → 완료 음성, "다크모드 켜줘",
  "클립보드 읽어줘", "단축어 목록", "음악에서 ~ 틀어줘".
- 풀 능력(F): `_can_use_tool` 단위 — 읽기셋 자동 허용, Bash/Write는
  confirm("네")→Allow·confirm("아니")→Deny·confirm 미주입→Deny(가짜 confirm
  주입). 라이브: "바탕화면에 메모 파일 만들어줘"(Write 음성확인) /
  "다운로드 폴더에 뭐 있어?"(Bash 음성확인 또는 Glob 자동).
