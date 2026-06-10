# 설계: 능동적 자비스 (실제 자비스 업그레이드 2단계)

날짜: 2026-06-10
상태: 사용자 승인됨
선행: 1단계 웨이크워드+연속대화 (2026-06-10-wake-word-design.md, 가동 중)

## 목표

자비스가 먼저 말을 건다. 아침 브리핑, 배터리 경고, 미리알림/일정 임박 알림,
부팅·복귀 인사 — "영화에서 하는 것 최대한"(사용자 요구). 모든 발화는 기존
두뇌를 거쳐 자비스 위트(영어 발화 + 한국어 자막)로 나간다.

## 결정 사항 (사용자 선택)

- 접근법: **A. 인프로세스 엔진** — 별도 프로세스/launchd/알림센터 후킹 없음
- 아침 브리핑: **그날 첫 화면 잠금 해제 시** (허공 발화 방지)
- 에티켓: **대화 중에만 보류** — 그 외 제약(심야 금지 등)은 두지 않음
  (단, 노브는 만들어 둔다)

## 아키텍처

```
감시자(Monitor)들 ── Announcement ──▶ ProactiveEngine ── IDLE일 때 ──▶ 두뇌 → 음성+자막
  배터리(60초 폴링)                     │ 우선순위 큐                      └ 발화 후 follow-up 창
  화면 잠금/해제(5초)                   │ 종류별 쿨다운
  미리알림(60초)                        │ 만료 폐기
  캘린더(5분)                           └ 대화 중 보류
```

새 패키지 `jarvis/proactive/`:

- `events.py` — `Announcement(kind, prompt, priority, expires_at)` 데이터클래스.
  `prompt`는 두뇌에 줄 한국어 이벤트 설명(예: "배터리 18%, 방전 중").
- `monitors.py` — 폴링 감시자들. 전부 주입형 `runner`(subprocess/osascript)와
  주입형 시계로 단위 테스트 가능. 각 감시자는 상태를 기억해 "돌파/전이
  시점"에만 이벤트를 낸다(스팸 금지).
  - `BatteryMonitor`: `pmset -g batt` 파싱. 20/10/5% 하향 돌파 각 1회,
    전원 연결 전이, 100% 도달 1회.
  - `SessionMonitor`: Quartz `CGSessionCopyCurrentDictionary` 폴링으로
    잠금/해제 전이 감지. 해제 시: 그날 첫 해제면 `briefing`, 아니면
    쿨다운(기본 4h) 지난 경우 `greet_back`.
    **기동 시 화면이 이미 해제 상태이고 그날 브리핑을 아직 안 했다면 이를
    "그날 첫 해제"로 간주**(아침에 자비스를 막 켠 경우 브리핑이 영영 안
    뜨는 구멍 방지). 이 경우 `boot_greet`는 생략한다 — 브리핑이 인사를
    겸한다(이중 인사 방지).
  - `RemindersMonitor`: 미리알림 due 임박(기본 10분 전), id 기반 중복 방지.
  - `CalendarMonitor`: 오늘 일정 시작 임박(기본 10분 전), id 기반 중복 방지.
- `engine.py` — `ProactiveEngine`: 감시자 폴링 태스크 + 우선순위 큐 + 전달
  정책. 오케스트레이터가 시작/정지.

## 이벤트 카탈로그 (1차)

| kind | 트리거 | 우선순위 | 만료 |
|---|---|---|---|
| `battery_critical` | 5% 하향 돌파 | 0 (최고) | 10분 |
| `reminder_due` | due 10분 전 | 1 | due 시각 |
| `event_soon` | 일정 시작 10분 전 | 1 | 시작 시각 |
| `battery_low` | 20%/10% 하향 돌파 | 2 | 10분 |
| `charge_full` | 100% 도달 | 3 | 10분 |
| `charger_on` | 전원 연결 | 3 | 5분 |
| `briefing` | 그날 첫 잠금 해제 | 2 | 2시간 |
| `boot_greet` | 자비스 기동 직후 | 3 | 5분 |
| `greet_back` | 잠금 해제(쿨다운 4h) | 4 | 5분 |
| `late_night` | 02시 이후 사용 중 1회 | 4 | 1시간 |

`late_night`는 기본 off(`proactive_late_night=False`).

## 전달 정책

- 전달 조건: `state == IDLE` (대화/응답 중 보류). follow-up 창(attentive)
  중에는 전달해도 된다 — 사용자가 고른 유일한 제약은 "대화 중 대기".
- 같은 kind 연속 전달 사이 쿨다운(기본 10분, 인사류는 별도).
- 만료된 알림은 버린다(오래된 브리핑/지나간 일정 금지).
- 즉답 필러 없음(`_pipeline_text`의 ack 생략 경로) — 기다리는 사람이 없다.
- 발화 종료 후 기존 `_enter_attentive()` 그대로 → 즉시 되묻기 가능.

## 두뇌 연동

- 오케스트레이터에 `announce(prompt)` 추가: `_pipeline_text`를 ack 없이
  타는 경로. 프롬프트 형식:
  `[SYSTEM EVENT] 주인님이 묻지 않았지만 먼저 알려라: <이벤트 설명>`
- 두뇌 지침(_GUIDANCE_EN)에 시스템 이벤트 룰 1줄 추가: 짧게(1~2문장),
  위트 유지, 영어 발화 + [KO] 자막 동일.
- **브리핑**: 이벤트 설명에 "오늘 브리핑을 하라 — 날씨/미리알림/일정 도구를
  사용해서"를 넣어 두뇌가 도구를 직접 호출해 구성한다.

## 새 MCP 도구 (읽기 전용, 3단계 선행 투자)

`jarvis/tools/jarvis_mcp.py`에 추가, 주입형 runner + 단위 테스트:
- `get_reminders(hours)` — 다가오는 미리알림 목록 (AppleScript Reminders)
- `get_calendar_events(hours)` — 오늘/다가오는 일정 (AppleScript Calendar)
평소 대화("오늘 일정 뭐야?")에서도 쓰인다. JARVIS_TOOL_NAMES 등록.

## 설정 (config.py)

- `proactive_enabled: bool = True`
- `battery_warn_levels: list[int] = [20, 10, 5]`
- `reminder_lead_min: int = 10`, `event_lead_min: int = 10`
- `greet_cooldown_h: float = 4.0`
- `briefing_expire_h: float = 2.0`
- `proactive_cooldown_min: int = 10` (kind별 기본)
- `proactive_late_night: bool = False`

## 에러 처리

- 감시자 한 개의 실패(AppleScript 오류, pmset 파싱 실패)는 그 감시자만
  다음 폴링에서 재시도 — 엔진/다른 감시자에 전파 금지(웨이크 루프와 동일
  원칙). 미리알림/캘린더 권한이 없으면 해당 감시자 자동 비활성+1회 안내.
- 캘린더/미리알림 첫 접근 시 macOS 자동화 권한 팝업 — 부팅 직후가 아니라
  첫 폴링 시점에 뜬다(문서화).

## 테스트

- 감시자: 가짜 runner/시계로 전이 감지(돌파 1회성, 중복 방지, 쿨다운).
- 엔진: 우선순위 순서, 만료 폐기, IDLE 대기 후 전달, kind 쿨다운.
- 오케스트레이터: announce가 ack 없이 발화하고 follow-up 창을 여는지.
- 도구: get_reminders/get_calendar_events 파싱(주입 runner).
- 라이브: 부팅 인사, 잠금/해제 브리핑·인사, 배터리 문턱(클램셸로 유도
  어려우면 문턱값 임시 상향으로 검증), 미리알림 5분 뒤 생성해 알림 확인.
