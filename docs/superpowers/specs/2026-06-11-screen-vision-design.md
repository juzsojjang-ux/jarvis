# 설계: 화면 시야 + 제어 (3단계 능력 확장 — 3c, 로드맵 마지막)

날짜: 2026-06-11
상태: 사용자 승인됨("알아서 다 해" + "스크린샷 말고 계속 보고 제어까지")
선행: 3a 풀 도구 개방(Read 이미지 비전), 3b 정보 팩 (가동 중)

## 목표

자비스가 **화면을 계속 보면서 제어**한다 — 화면 공유 + 원격 조작 느낌.
"지금 화면 뭐 있어?"(보기)부터 "이 양식 채워줘 / 저거 클릭해줘"(제어)까지.

## 핵심 통찰

풀 도구 개방(3a)으로 두뇌가 **Read로 이미지를 시각적으로 본다**(별도 비전 모델
불필요). 두뇌의 에이전트 루프(max_turns=20)는 **캡처→보기→행동→다시 캡처**를
반복할 수 있다 — 이게 "화면 공유하며 조작"의 실체다. 진짜 연속 영상 스트리밍은
구독으로 불가능하지만, 이 캡처-행동 루프가 같은 체감을 준다.

## 두 축: 눈과 손

### 눈 — `capture_screen(region="full")`
- `screencapture -x <path>`(무음) → `~/.jarvis/screenshots/shot.png`(덮어씀).
  경로 반환 → 두뇌가 Read로 본다. 읽기 전용·무해 → mcp__jarvis__ 자동 허용.
- region v1=full. macOS **화면 기록 권한** 필요(첫 사용 시 팝업).

### 손 — 화면 제어 도구 (cliclick 기반)
좌표 기반 GUI 조작. `cliclick`(brew) 사용, 미설치 시 "brew install cliclick"
안내. 전부 주입형 runner, 절대 raise 안 함:
- `click_at(x, y)` — 좌클릭 (`cliclick c:x,y`)
- `double_click_at(x, y)` — 더블클릭 (`cliclick dc:x,y`)
- `right_click_at(x, y)` — 우클릭 (`cliclick rc:x,y`)
- `move_mouse(x, y)` — 이동 (`cliclick m:x,y`)
- `type_text(text)` — 키보드 입력 (`cliclick t:text`)
- `press_key(key)` — 특수키 (`cliclick kp:key`; return/tab/esc/space/arrow 등)
- `scroll(amount)` — 스크롤 (`cliclick s:amount`, 양수 위/음수 아래... 실제
  방향은 구현 시 확정)
→ 하나의 도구 `screen_control(action, x?, y?, text?, key?, amount?)`로 묶어
   디스패치(도구 수 폭증 방지). action: click/double_click/right_click/move/
   type/key/scroll.

## 안전 모델 — "화면 제어 모드" 게이트 (핵심)

화면 제어는 아무거나 클릭/입력할 수 있어 지금까지 중 가장 위험하다. 통역
모드처럼 **명시적 모드 게이트**로 보호:
- `screen_control_enabled` 런타임 플래그(기본 False). 오케스트레이터가 보유.
- "화면 제어 모드 켜줘" → on, "꺼줘" → off (interpret과 같은 토글 패턴).
  켜질 때 음성 안내 + **5분 자동 만료**(켜둔 채 잊는 위험 방지).
- `screen_control` 도구는 **플래그가 off면 거부**("화면 제어 모드를 먼저
  켜주세요"). 모드 진입 자체가 사용자 동의 — 모드 내에선 매 동작 음성 확인
  없이 유려하게(확인하면 화면 조작이 못 쓸 만큼 느려짐).
- 사용자는 자기 화면을 **실시간으로 보며** 언제든 마우스/키보드로 끼어들거나
  "꺼줘"로 중단 가능 — 이게 실질 안전망.
- `capture_screen`(보기)은 무해하므로 모드와 무관하게 항상 가능.
- 플래그 상태는 도구가 읽어야 하므로 **모듈 공유 객체**(TimerBoard·DEFAULT_BOARD
  패턴 재사용): `jarvis/core/control_gate.py`의 `CONTROL_GATE`(스레드 안전한
  on/off + 만료 시각). 오케스트레이터가 토글, screen_control 도구가 확인.

## 데이터 흐름

```
"화면 제어 모드 켜줘" → 오케스트레이터 CONTROL_GATE.enable(5분) + 안내 발화
"이 양식 첫 칸에 내 이름 적어줘" → 두뇌
   → capture_screen → Read(이미지) → 칸 좌표 파악
   → screen_control(action="click", x, y)  [게이트 on → 실행]
   → screen_control(action="type", text="이성재")
   → capture_screen → 확인 → 발화
"화면 제어 모드 꺼줘" → CONTROL_GATE.disable + 안내
```

## 컴포넌트 정리

- `jarvis/core/control_gate.py`: `ControlGate`(enable(ttl)/disable/is_on(now)/
  락 보호) + 모듈 싱글턴 `CONTROL_GATE`.
- `jarvis/tools/jarvis_mcp.py`: `capture_screen_action`, `screen_control_action`
  (게이트 확인 + cliclick 디스패치) + @tool 2개 + JARVIS_TOOL_NAMES.
- `jarvis/core/orchestrator.py`: `_control_command(text)`("화면 제어"+켜/꺼) +
  `_toggle_control` — interpret 토글과 같은 모양. `_pipeline_text` 진입부 검사
  **순서**: ① control 토글("화면 제어"+켜/꺼) → ② interpret 토글("통역"+켜/꺼)
  → ③ interpret_mode면 통역 턴 → ④ 일반 두뇌. control 명령은 "화면 제어"를,
  interpret는 "통역"을 요구하므로 서로 안 겹친다(둘 다 독립 토글). 화면 제어
  모드는 두뇌 우회가 아니라 **두뇌가 도구를 쓰는 평소 경로** — interpret처럼
  턴을 가로채지 않고, 게이트 플래그만 연다. 따라서 control_mode가 켜져도 ③/④는
  평소대로(두뇌가 capture_screen+screen_control 호출).
- 두뇌 지침 1문장: 화면 질문이면 capture_screen→Read; 화면 조작이 필요하면
  먼저 화면을 캡처해 좌표를 보고 screen_control을 쓰되, 사용자가 "화면 제어
  모드"를 켜둬야 동작함을 알라.
- 설정: `screen_control_ttl_s: float = 300.0`(모드 자동 만료).

## 에러 처리
- screencapture/cliclick 실패·미설치 → 안내 문자열(raise 금지). cliclick 미설치
  → "화면 제어에는 cliclick이 필요합니다(brew install cliclick)".
- 게이트 off에서 screen_control 호출 → 거부 안내(실행 안 함).
- 좌표 파싱 실패(x/y 정수 아님) → 안내.

## 테스트
- `ControlGate`: enable 후 is_on True, ttl 경과 후 False, disable 즉시 False
  (주입 시계).
- `capture_screen_action`: runner에 `screencapture -x <path>`, 경로 반환, 디렉터리
  생성, 실패 안내.
- `screen_control_action`: 게이트 off→거부 / on→action별 cliclick 명령 검증
  (click `c:x,y`, type `t:text`, key `kp:key`...) / cliclick 미설치(FileNotFound)
  → 안내 / 좌표 불량 안내. 게이트는 주입.
- 오케스트레이터: `_control_command` 토글 매칭, `_toggle_control`이 CONTROL_GATE
  enable/disable + 안내 발화, ttl 전달. interpret과 독립(둘 다 모드여도 충돌 없음
  — control 명령 우선순위 확인).
- JARVIS_TOOL_NAMES에 capture_screen·screen_control 등록.
- 라이브: "화면 제어 모드 켜줘" → "메모 앱 열어서 안녕 적어줘" → 캡처·클릭·입력
  → "꺼줘". 권한(화면기록+손쉬운사용) 팝업 허용.
