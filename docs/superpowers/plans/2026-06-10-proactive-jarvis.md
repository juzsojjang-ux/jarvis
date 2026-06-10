# 능동적 자비스 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 자비스가 먼저 말을 건다 — 아침 브리핑(그날 첫 잠금 해제), 배터리 경고/충전 알림, 미리알림·일정 임박 알림, 부팅·복귀 인사. 전부 기존 두뇌를 거쳐 위트 있는 영어 발화+한국어 자막.

**Architecture:** 자비스 프로세스 안에 `ProactiveEngine`(asyncio 태스크)이 감시자들을 주기 폴링(subprocess는 to_thread)하고, 이벤트를 우선순위 큐에 넣었다가 오케스트레이터가 IDLE일 때 `announce()`로 전달한다. announce는 즉답 필러 없이 `_pipeline_text`를 타고, `[SYSTEM EVENT]` 프리픽스를 본 두뇌가 능동 알림 톤으로 말한다. 발화 후 기존 follow-up 창이 열려 즉시 되묻기가 된다.

**Tech Stack:** asyncio, pmset(배터리), Quartz CGSessionCopyCurrentDictionary(잠금 감지 — 메인 venv에 이미 import 가능 확인됨), osascript AppleScript(미리알림/캘린더), 기존 SubscriptionBrain/MCP 패턴.

**스펙:** `docs/superpowers/specs/2026-06-10-proactive-jarvis-design.md`

**프로젝트 약속:** 테스트 `cd ~/jarvis && .venv/bin/python -m pytest <path> -v` / 린트 `.venv/bin/ruff check jarvis tests`(line 100) / 커밋 한국어 + `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` 푸터 / 주석은 '왜'만 / **라이브 앱 실행·재시작 금지(자비스가 떠 있음), 테스트에서 실제 장치·osascript 절대 호출 금지(runner 주입)**.

## 파일 구조

| 파일 | 책임 |
|---|---|
| Create `jarvis/proactive/__init__.py` | 패키지 (빈 파일) |
| Create `jarvis/proactive/events.py` | `Announcement` 데이터클래스 |
| Create `jarvis/proactive/sources.py` | 미리알림/캘린더 AppleScript 실행+파싱 (monitor와 MCP 도구가 공유) |
| Create `jarvis/proactive/monitors.py` | Battery/Session/Reminders/Calendar/LateNight 감시자 + `build_monitors` |
| Create `jarvis/proactive/engine.py` | ProactiveEngine — 폴링·큐·전달 정책 |
| Modify `jarvis/core/config.py` | proactive 설정 8개 |
| Modify `jarvis/core/orchestrator.py` | `announce()`/`_handle_announce`/`_can_announce`, `_pipeline_text(ack=)`, run()에서 엔진 시작 |
| Modify `jarvis/brain/subscription.py` | [SYSTEM EVENT] 지침 1문장 (EN/KO) |
| Modify `jarvis/tools/jarvis_mcp.py` | `get_reminders`/`get_calendar_events` 읽기 도구 |
| Modify `jarvis/__main__.py` | 엔진 조립·주입 |
| Test | `tests/proactive/test_{events,sources,monitors,engine}.py`, 기존 테스트 파일 확장 |

---

### Task 1: Announcement 데이터클래스

**Files:**
- Create: `jarvis/proactive/__init__.py` (빈 파일)
- Create: `jarvis/proactive/events.py`
- Test: `tests/proactive/test_events.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/proactive/test_events.py
from jarvis.proactive.events import Announcement


def test_expiry():
    a = Announcement(kind="briefing", prompt="브리핑", priority=2,
                     created_at=100.0, expires_at=200.0)
    assert not a.expired(150.0)
    assert a.expired(200.0)


def test_fields_round_trip():
    a = Announcement(kind="battery_low", prompt="배터리 18%", priority=2,
                     created_at=0.0, expires_at=600.0)
    assert a.kind == "battery_low" and a.priority == 2 and "18" in a.prompt
```

- [ ] **Step 2: 실패 확인** — `.venv/bin/python -m pytest tests/proactive/test_events.py -v` → ModuleNotFoundError

- [ ] **Step 3: 구현**

```python
# jarvis/proactive/events.py
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Announcement:
    """능동 알림 한 건. priority는 낮을수록 급함(0=배터리 위험). 시각은 엔진이
    쓰는 단조 시계(clock) 기준 — 벽시계와 섞지 말 것."""

    kind: str
    prompt: str       # 두뇌에 줄 한국어 이벤트 설명
    priority: int
    created_at: float
    expires_at: float

    def expired(self, now: float) -> bool:
        return now >= self.expires_at
```

`jarvis/proactive/__init__.py`는 빈 파일로 생성.

- [ ] **Step 4: 통과 확인** — 2 PASS
- [ ] **Step 5: Commit** — `git add jarvis/proactive tests/proactive && git commit -m "feat(proactive): Announcement 데이터클래스"` (+푸터)

---

### Task 2: 설정 8종

**Files:**
- Modify: `jarvis/core/config.py` (M3 wake 블록과 HUD 블록 사이에 삽입)
- Modify: `tests/core/test_config_m2.py` (테스트 추가)

- [ ] **Step 1: 실패하는 테스트 추가** — tests/core/test_config_m2.py 끝에:

```python
def test_proactive_defaults():
    s = Settings()
    assert s.proactive_enabled is True
    assert s.battery_warn_levels == [20, 10, 5]
    assert s.reminder_lead_min == 10 and s.event_lead_min == 10
    assert s.greet_cooldown_h == 4.0
    assert s.briefing_expire_h == 2.0
    assert s.proactive_cooldown_min == 10
    assert s.proactive_late_night is False
```

- [ ] **Step 2: 실패 확인** — AttributeError
- [ ] **Step 3: 구현** — config.py의 `vad_model_path` 줄 아래(HUD 블록 위)에:

```python
    # --- M4 능동적 자비스 (2단계) ---
    # 먼저 말 거는 자비스: 브리핑/배터리/미리알림·일정/인사. 대화 중엔 보류.
    proactive_enabled: bool = True
    battery_warn_levels: list[int] = [20, 10, 5]  # 하향 돌파마다 1회 경고
    reminder_lead_min: int = 10        # 미리알림 due 몇 분 전에 알릴지
    event_lead_min: int = 10           # 캘린더 일정 시작 몇 분 전에 알릴지
    greet_cooldown_h: float = 4.0      # 복귀 인사 최소 간격
    briefing_expire_h: float = 2.0     # 묵은 브리핑 폐기
    proactive_cooldown_min: int = 10   # 같은 종류 알림 최소 간격
    proactive_late_night: bool = False  # 새벽 2시 "주무시죠" 한마디(기본 꺼짐)
```

- [ ] **Step 4: 통과 확인** — config 테스트 전체 PASS
- [ ] **Step 5: Commit** — `feat(config): 능동적 자비스 설정 추가`

---

### Task 3: sources.py — 미리알림/캘린더 읽기 (감시자·도구 공용)

**Files:**
- Create: `jarvis/proactive/sources.py`
- Test: `tests/proactive/test_sources.py`

출력 계약: `fetch_reminders(window_s, runner)` / `fetch_events(window_s, runner)` →
`list[tuple[id, 제목, 남은초]]`. AppleScript 문자열은 환경에 따라 구현자가 다듬어도
되지만(아래는 검증된 형태) **출력 라인 포맷 `id|제목|남은초`와 함수 시그니처는
계약**이다. osascript 호출엔 `timeout=15`를 건다(캘린더 앱은 느릴 수 있다).

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/proactive/test_sources.py
from types import SimpleNamespace

from jarvis.proactive.sources import fetch_events, fetch_reminders


def _runner_returning(stdout):
    calls = []

    def runner(cmd, capture_output=True, text=True, timeout=None):
        calls.append((cmd, timeout))
        return SimpleNamespace(stdout=stdout, returncode=0)

    runner.calls = calls
    return runner


def test_fetch_reminders_parses_lines():
    r = _runner_returning("id-1|회의 자료 제출|540\nid-2|약 먹기|3000\n")
    items = fetch_reminders(3600, runner=r)
    assert items == [("id-1", "회의 자료 제출", 540), ("id-2", "약 먹기", 3000)]
    cmd, timeout = r.calls[0]
    assert cmd[0] == "osascript" and timeout == 15


def test_fetch_skips_malformed_lines():
    r = _runner_returning("쓰레기줄\nid-1|제목|60\n|빈아이디|10\nid-2|음수|-5\n")
    items = fetch_reminders(3600, runner=r)
    assert items == [("id-1", "제목", 60)]   # 형식 불량·빈 id·지난 항목 제외


def test_fetch_events_parses_lines():
    r = _runner_returning("uid-9|팀 미팅|480\n")
    assert fetch_events(7200, runner=r) == [("uid-9", "팀 미팅", 480)]


def test_fetch_returns_empty_on_runner_error():
    def boom(cmd, capture_output=True, text=True, timeout=None):
        raise RuntimeError("osascript fail")

    assert fetch_reminders(3600, runner=boom) == []
    assert fetch_events(3600, runner=boom) == []
```

- [ ] **Step 2: 실패 확인** — ModuleNotFoundError
- [ ] **Step 3: 구현**

```python
# jarvis/proactive/sources.py
"""미리알림/캘린더를 AppleScript로 읽는다 — 감시자(임박 알림)와 MCP 도구
(브리핑·"오늘 일정 뭐야?")가 같은 페처를 쓴다. 출력 계약: (id, 제목, 남은초).
첫 호출 시 macOS 자동화 권한 팝업이 뜰 수 있다(부팅이 아니라 첫 폴링 시점)."""
from __future__ import annotations

import subprocess

_REMINDERS_SCRIPT = """
set out to ""
set nowD to current date
tell application "Reminders"
    repeat with r in (reminders whose completed is false)
        try
            set d to due date of r
            if d is not missing value then
                set secs to (d - nowD) as integer
                if secs > 0 and secs < {window} then
                    set out to out & (id of r) & "|" & (name of r) & "|" & secs & linefeed
                end if
            end if
        end try
    end repeat
end tell
return out
"""

_EVENTS_SCRIPT = """
set out to ""
set nowD to current date
set endD to nowD + {window}
tell application "Calendar"
    repeat with c in calendars
        try
            repeat with e in (events of c whose start date is greater than nowD ¬
                              and start date is less than endD)
                set secs to ((start date of e) - nowD) as integer
                set out to out & (uid of e) & "|" & (summary of e) & "|" & secs & linefeed
            end repeat
        end try
    end repeat
end tell
return out
"""


def _run_script(script: str, runner) -> list[tuple[str, str, int]]:
    try:
        res = runner(["osascript", "-e", script], capture_output=True, text=True, timeout=15)
        raw = (getattr(res, "stdout", "") or "")
    except Exception:  # noqa: BLE001 - 권한 거부/타임아웃: 이번 폴링만 빈손
        return []
    items: list[tuple[str, str, int]] = []
    for line in raw.splitlines():
        parts = line.split("|")
        if len(parts) != 3:
            continue
        ident, title, secs_s = parts[0].strip(), parts[1].strip(), parts[2].strip()
        try:
            secs = int(secs_s)
        except ValueError:
            continue
        if ident and secs > 0:
            items.append((ident, title, secs))
    return items


def fetch_reminders(window_s: int, runner=subprocess.run) -> list[tuple[str, str, int]]:
    return _run_script(_REMINDERS_SCRIPT.replace("{window}", str(int(window_s))), runner)


def fetch_events(window_s: int, runner=subprocess.run) -> list[tuple[str, str, int]]:
    return _run_script(_EVENTS_SCRIPT.replace("{window}", str(int(window_s))), runner)
```

주의: AppleScript의 `¬`(줄 연속)와 따옴표가 그대로 보존되어야 한다. `.format()`이
아니라 `.replace("{window}", ...)`를 쓴다 — 스크립트에 중괄호가 더 생겨도 안전.

- [ ] **Step 4: 통과 확인** — 4 PASS. 추가로 수동 1회(라이브 환경 검증, 실패해도 커밋은 진행하되 보고):
`.venv/bin/python -c "from jarvis.proactive.sources import fetch_reminders; print(fetch_reminders(86400))"`
(권한 팝업이 뜨면 그 사실을 보고에 적는다)
- [ ] **Step 5: Commit** — `feat(proactive): 미리알림/캘린더 AppleScript 페처`

---

### Task 4: BatteryMonitor

**Files:**
- Create: `jarvis/proactive/monitors.py` (이 태스크는 BatteryMonitor + 공통 베이스만)
- Test: `tests/proactive/test_monitors.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/proactive/test_monitors.py
from types import SimpleNamespace

from jarvis.proactive.monitors import BatteryMonitor


def _pmset_runner(text_out):
    def runner(cmd, capture_output=True, text=True, timeout=None):
        return SimpleNamespace(stdout=text_out, returncode=0)
    return runner


def _batt(pct, charging=False):
    src = "AC Power" if charging else "Battery Power"
    state = "charging" if charging else "discharging"
    return (f"Now drawing from '{src}'\n -InternalBattery-0 (id=1)\t{pct}%; "
            f"{state}; 3:00 remaining present: true\n")


def test_battery_warns_once_per_level_crossing():
    mon = BatteryMonitor(levels=[20, 10, 5])
    mon._runner = _pmset_runner(_batt(25))
    assert mon.poll() == []                       # 25%: 경고 없음
    mon._runner = _pmset_runner(_batt(19))
    out = mon.poll()
    assert len(out) == 1 and out[0].kind == "battery_low" and "19" in out[0].prompt
    mon._runner = _pmset_runner(_batt(18))
    assert mon.poll() == []                       # 같은 문턱 반복 경고 금지
    mon._runner = _pmset_runner(_batt(9))
    assert mon.poll()[0].kind == "battery_low"    # 10% 문턱
    mon._runner = _pmset_runner(_batt(4))
    assert mon.poll()[0].kind == "battery_critical"  # 5% 문턱은 critical


def test_charger_transitions():
    mon = BatteryMonitor(levels=[20, 10, 5])
    mon._runner = _pmset_runner(_batt(18))
    mon.poll()                                    # 방전 중 18% (경고 1회 소모)
    mon._runner = _pmset_runner(_batt(18, charging=True))
    out = mon.poll()
    assert [a.kind for a in out] == ["charger_on"]
    mon._runner = _pmset_runner(_batt(100, charging=True))
    out = mon.poll()
    assert [a.kind for a in out] == ["charge_full"]
    mon._runner = _pmset_runner(_batt(100, charging=True))
    assert mon.poll() == []                       # 완충 알림 1회만
    # 다시 뽑았다가 떨어지면 경고가 부활해야 한다
    mon._runner = _pmset_runner(_batt(19))
    assert mon.poll()[0].kind == "battery_low"


def test_battery_unreadable_is_silent():
    mon = BatteryMonitor(levels=[20, 10, 5])
    mon._runner = _pmset_runner("garbage")
    assert mon.poll() == []
```

- [ ] **Step 2: 실패 확인** — ModuleNotFoundError
- [ ] **Step 3: 구현**

```python
# jarvis/proactive/monitors.py
"""능동 알림 감시자들. 각 poll()은 '전이가 일어난 순간'에만 Announcement를
돌려준다(반복 스팸 금지). subprocess/AppleScript는 전부 주입형 runner — 엔진이
to_thread에서 부르므로 여기선 동기로 단순하게 쓴다."""
from __future__ import annotations

import re
import subprocess
import time
from datetime import date, datetime

from .events import Announcement
from .sources import fetch_events, fetch_reminders

_TEN_MIN = 600.0


class BatteryMonitor:
    """pmset -g batt 파싱. 문턱 하향 돌파/전원 전이/완충 시각각 1회."""

    interval_s = 60.0

    def __init__(self, levels=(20, 10, 5), runner=subprocess.run,
                 clock=time.monotonic):
        self._levels = sorted(levels, reverse=True)   # [20, 10, 5]
        self._runner = runner
        self._clock = clock
        self._prev_pct: int | None = None
        self._prev_ac: bool | None = None
        self._warned: set[int] = set()
        self._full_announced = False

    def _read(self) -> tuple[int, bool] | None:
        try:
            res = self._runner(["pmset", "-g", "batt"], capture_output=True,
                               text=True, timeout=10)
            out = (getattr(res, "stdout", "") or "")
        except Exception:  # noqa: BLE001 - 이번 폴링만 건너뜀
            return None
        m = re.search(r"(\d+)%", out)
        if not m:
            return None
        return int(m.group(1)), ("AC Power" in out)

    def poll(self) -> list[Announcement]:
        read = self._read()
        if read is None:
            return []
        pct, on_ac = read
        now = self._clock()
        out: list[Announcement] = []
        if self._prev_ac is not None and on_ac != self._prev_ac:
            if on_ac:
                out.append(Announcement("charger_on", f"전원이 연결됐다 (배터리 {pct}%)",
                                        3, now, now + 300))
                self._warned.clear()              # 충전 시작: 경고 카운터 리셋
            self._full_announced = False
        if on_ac and pct >= 100 and not self._full_announced:
            out.append(Announcement("charge_full", "배터리 완충(100%)", 3, now, now + _TEN_MIN))
            self._full_announced = True
        if not on_ac and self._prev_pct is not None:
            for lv in self._levels:
                if self._prev_pct > lv >= pct and lv not in self._warned:
                    kind = "battery_critical" if lv <= 5 else "battery_low"
                    prio = 0 if lv <= 5 else 2
                    out.append(Announcement(
                        kind, f"배터리가 {pct}%까지 떨어졌다(방전 중)", prio,
                        now, now + _TEN_MIN))
                    self._warned.add(lv)
        if not on_ac:
            self._full_announced = False
        self._prev_pct, self._prev_ac = pct, on_ac
        return out
```

- [ ] **Step 4: 통과 확인** — 3 PASS
- [ ] **Step 5: Commit** — `feat(proactive): 배터리 감시자 — 문턱/전원/완충 전이 감지`

---

### Task 5: SessionMonitor + LateNightMonitor

**Files:**
- Modify: `jarvis/proactive/monitors.py`
- Modify: `tests/proactive/test_monitors.py`

- [ ] **Step 1: 실패하는 테스트 추가**

```python
from jarvis.proactive.monitors import LateNightMonitor, SessionMonitor


class _FakeSession:
    """locked_fn/clock/today_fn 주입으로 시나리오 재현."""

    def __init__(self):
        self.locked = False
        self.t = 1000.0
        self.day = date(2026, 6, 10)


from datetime import date, datetime  # 파일 상단 import에 합쳐라


def _session_mon(fs, cooldown_h=4.0):
    return SessionMonitor(locked_fn=lambda: fs.locked, clock=lambda: fs.t,
                          today_fn=lambda: fs.day, greet_cooldown_s=cooldown_h * 3600,
                          briefing_expire_s=7200)


def test_first_poll_unlocked_emits_briefing_and_marks_day():
    fs = _FakeSession()
    mon = _session_mon(fs)
    out = mon.poll()
    assert [a.kind for a in out] == ["briefing"]   # 기동 시 이미 해제 = 그날 첫 해제
    assert mon.poll() == []                        # 같은 날 반복 금지


def test_unlock_transition_briefs_once_per_day_then_greets():
    fs = _FakeSession()
    fs.locked = True
    mon = _session_mon(fs)
    assert mon.poll() == []                        # 잠긴 채 시작: 아무 일 없음
    fs.locked = False
    assert [a.kind for a in mon.poll()] == ["briefing"]
    fs.locked = True; mon.poll()
    fs.t += 5 * 3600                               # 쿨다운(4h) 경과
    fs.locked = False
    assert [a.kind for a in mon.poll()] == ["greet_back"]
    fs.locked = True; mon.poll()
    fs.t += 600                                    # 쿨다운 미경과
    fs.locked = False
    assert mon.poll() == []


def test_new_day_briefs_again():
    fs = _FakeSession()
    mon = _session_mon(fs)
    mon.poll()                                     # 오늘 브리핑 소모
    fs.locked = True; mon.poll()
    fs.day = date(2026, 6, 11)
    fs.locked = False
    assert [a.kind for a in mon.poll()] == ["briefing"]


def test_late_night_once_when_enabled():
    fs = _FakeSession()
    mon = LateNightMonitor(locked_fn=lambda: fs.locked, clock=lambda: fs.t,
                           now_fn=lambda: datetime(2026, 6, 11, 2, 30),
                           today_fn=lambda: fs.day)
    out = mon.poll()
    assert [a.kind for a in out] == ["late_night"]
    assert mon.poll() == []                        # 하루 1회
```

- [ ] **Step 2: 실패 확인** — ImportError SessionMonitor
- [ ] **Step 3: 구현** — monitors.py에 추가:

```python
def _screen_locked() -> bool:
    """macOS 화면 잠금 여부 — Quartz 세션 사전. 메인 venv에서 import 확인됨."""
    import Quartz  # 지연 import: 테스트는 locked_fn 주입으로 우회

    d = Quartz.CGSessionCopyCurrentDictionary()
    return bool(d and d.get("CGSSessionScreenIsLocked", 0))


class SessionMonitor:
    """잠금/해제 전이 감지. 그날 첫 해제(기동 시 이미 해제 포함)=briefing,
    이후 해제는 쿨다운 지난 경우 greet_back."""

    interval_s = 5.0

    def __init__(self, *, locked_fn=_screen_locked, clock=time.monotonic,
                 today_fn=date.today, greet_cooldown_s=4 * 3600.0,
                 briefing_expire_s=7200.0):
        self._locked_fn = locked_fn
        self._clock = clock
        self._today = today_fn
        self._greet_cooldown_s = greet_cooldown_s
        self._briefing_expire_s = briefing_expire_s
        self._prev_locked: bool | None = None
        self._briefed_on: date | None = None
        self._last_greet = -1e12

    def _briefing(self, now: float) -> Announcement:
        self._briefed_on = self._today()
        return Announcement(
            "briefing",
            "오늘의 아침 브리핑을 하라 — get_weather, get_reminders, "
            "get_calendar_events 도구로 날씨·미리알림·오늘 일정을 모아 짧게 보고",
            2, now, now + self._briefing_expire_s)

    def poll(self) -> list[Announcement]:
        locked = bool(self._locked_fn())
        now = self._clock()
        out: list[Announcement] = []
        first = self._prev_locked is None
        unlocked_now = (self._prev_locked is True and not locked)
        if (first and not locked) or unlocked_now:
            if self._briefed_on != self._today():
                out.append(self._briefing(now))
                self._last_greet = now             # 브리핑이 인사를 겸한다
            elif unlocked_now and now - self._last_greet >= self._greet_cooldown_s:
                out.append(Announcement("greet_back", "주인님이 자리로 돌아왔다 — 짧게 맞이하라",
                                        4, now, now + 300))
                self._last_greet = now
        self._prev_locked = locked
        return out


class LateNightMonitor:
    """02~05시 사이에 화면이 깨어 있으면 하루 1회, 영화처럼 한마디."""

    interval_s = 300.0

    def __init__(self, *, locked_fn=_screen_locked, clock=time.monotonic,
                 now_fn=datetime.now, today_fn=date.today):
        self._locked_fn = locked_fn
        self._clock = clock
        self._now = now_fn
        self._today = today_fn
        self._nudged_on: date | None = None

    def poll(self) -> list[Announcement]:
        if self._nudged_on == self._today():
            return []
        if self._locked_fn():
            return []
        if not (2 <= self._now().hour < 5):
            return []
        self._nudged_on = self._today()
        now = self._clock()
        return [Announcement("late_night",
                             "새벽 2시가 넘었는데 주인님이 아직 깨어 있다 — 정중하지만 "
                             "위트 있게 취침을 권하라", 4, now, now + 3600)]
```

(파일 상단 import에 `date`, `datetime`이 이미 있는지 확인 — Task 4에서 넣었다.)

- [ ] **Step 4: 통과 확인** — monitors 테스트 전체 PASS
- [ ] **Step 5: Commit** — `feat(proactive): 세션(브리핑/복귀인사)·심야 감시자`

---

### Task 6: Reminders/Calendar 감시자 + build_monitors

**Files:**
- Modify: `jarvis/proactive/monitors.py`
- Modify: `tests/proactive/test_monitors.py`

- [ ] **Step 1: 실패하는 테스트 추가**

```python
from jarvis.proactive.monitors import CalendarMonitor, RemindersMonitor, build_monitors


def test_reminder_due_within_lead_announced_once():
    items = {"v": [("id-1", "회의 자료", 540)]}        # 9분 후 due
    mon = RemindersMonitor(lead_s=600, fetch=lambda w, runner=None: items["v"])
    out = mon.poll()
    assert len(out) == 1 and out[0].kind == "reminder_due" and "회의 자료" in out[0].prompt
    assert mon.poll() == []                            # 같은 id 재알림 금지
    items["v"] = [("id-1", "회의 자료", 400), ("id-2", "약", 7200)]
    assert mon.poll() == []                            # id-2는 lead 밖


def test_calendar_event_soon_announced_once():
    mon = CalendarMonitor(lead_s=600, fetch=lambda w, runner=None: [("u1", "팀 미팅", 300)])
    out = mon.poll()
    assert out[0].kind == "event_soon" and "팀 미팅" in out[0].prompt
    assert mon.poll() == []


def test_build_monitors_respects_late_night_flag():
    class _S:  # Settings 흉내 — 필요한 필드만
        battery_warn_levels = [20, 10, 5]
        reminder_lead_min = 10
        event_lead_min = 10
        greet_cooldown_h = 4.0
        briefing_expire_h = 2.0
        proactive_late_night = False

    kinds = [type(m).__name__ for m in build_monitors(_S())]
    assert "LateNightMonitor" not in kinds
    _S.proactive_late_night = True
    kinds = [type(m).__name__ for m in build_monitors(_S())]
    assert "LateNightMonitor" in kinds
```

- [ ] **Step 2: 실패 확인** — ImportError
- [ ] **Step 3: 구현** — monitors.py에 추가:

```python
class _DueMonitor:
    """임박 항목 감시 공통: fetch가 (id, 제목, 남은초)를 주면 lead 이내 항목을
    id당 1회 알린다."""

    interval_s = 60.0

    def __init__(self, *, kind: str, what: str, lead_s: float, fetch,
                 clock=time.monotonic):
        self._kind = kind
        self._what = what
        self._lead_s = lead_s
        self._fetch = fetch
        self._clock = clock
        self._announced: set[str] = set()

    def poll(self) -> list[Announcement]:
        items = self._fetch(int(self._lead_s * 2))
        now = self._clock()
        live_ids = {i for i, _, _ in items}
        self._announced &= live_ids               # 사라진 항목은 셋에서 정리
        out: list[Announcement] = []
        for ident, title, secs in items:
            if secs <= self._lead_s and ident not in self._announced:
                mins = max(1, secs // 60)
                out.append(Announcement(
                    self._kind, f"{mins}분 뒤 {self._what}: {title}", 1,
                    now, now + secs))
                self._announced.add(ident)
        return out


class RemindersMonitor(_DueMonitor):
    def __init__(self, *, lead_s: float, fetch=fetch_reminders, clock=time.monotonic):
        super().__init__(kind="reminder_due", what="미리알림", lead_s=lead_s,
                         fetch=fetch, clock=clock)


class CalendarMonitor(_DueMonitor):
    interval_s = 300.0

    def __init__(self, *, lead_s: float, fetch=fetch_events, clock=time.monotonic):
        super().__init__(kind="event_soon", what="일정 시작", lead_s=lead_s,
                         fetch=fetch, clock=clock)


def build_monitors(settings) -> list:
    """설정으로 감시자 세트를 조립한다(엔진/배선에서 호출)."""
    mons: list = [
        BatteryMonitor(levels=settings.battery_warn_levels),
        SessionMonitor(greet_cooldown_s=settings.greet_cooldown_h * 3600,
                       briefing_expire_s=settings.briefing_expire_h * 3600),
        RemindersMonitor(lead_s=settings.reminder_lead_min * 60),
        CalendarMonitor(lead_s=settings.event_lead_min * 60),
    ]
    if settings.proactive_late_night:
        mons.append(LateNightMonitor())
    return mons
```

- [ ] **Step 4: 통과 확인** — monitors 테스트 전체 PASS
- [ ] **Step 5: Commit** — `feat(proactive): 미리알림/일정 임박 감시자 + build_monitors`

---

### Task 7: MCP 읽기 도구 get_reminders / get_calendar_events

**Files:**
- Modify: `jarvis/tools/jarvis_mcp.py`
- Modify: `tests/tools/test_jarvis_mcp.py` (기존 파일 끝에 추가 — 먼저 READ해서 기존 스타일 확인)

- [ ] **Step 1: 실패하는 테스트 추가** — tests/tools/test_jarvis_mcp.py 끝에:

```python
def test_reminders_text_lists_upcoming():
    from jarvis.tools.jarvis_mcp import reminders_text
    items = [("id-1", "회의 자료 제출", 540), ("id-2", "약 먹기", 7200)]
    out = reminders_text(fetch=lambda w, runner=None: items)
    assert "회의 자료 제출" in out and "약 먹기" in out and "9분" in out


def test_reminders_text_empty():
    from jarvis.tools.jarvis_mcp import reminders_text
    assert "없" in reminders_text(fetch=lambda w, runner=None: [])


def test_calendar_text_lists_events():
    from jarvis.tools.jarvis_mcp import calendar_text
    out = calendar_text(fetch=lambda w, runner=None: [("u1", "팀 미팅", 1800)])
    assert "팀 미팅" in out and "30분" in out


def test_new_tools_registered():
    from jarvis.tools.jarvis_mcp import JARVIS_TOOL_NAMES
    assert "mcp__jarvis__get_reminders" in JARVIS_TOOL_NAMES
    assert "mcp__jarvis__get_calendar_events" in JARVIS_TOOL_NAMES
```

- [ ] **Step 2: 실패 확인** — ImportError reminders_text
- [ ] **Step 3: 구현** — jarvis_mcp.py에 추가. 파일 상단 import에:

```python
from ..proactive.sources import fetch_events, fetch_reminders
```

액션 함수들(`battery_action` 근처에):

```python
def _fmt_due(title: str, secs: int) -> str:
    mins = max(1, secs // 60)
    return f"{title} — {mins // 60}시간 {mins % 60}분 후" if mins >= 60 else f"{title} — {mins}분 후"


def reminders_text(hours: Any = 24, fetch=fetch_reminders) -> str:
    try:
        h = max(1, min(168, int(hours)))
    except (TypeError, ValueError):
        h = 24
    items = fetch(h * 3600)
    if not items:
        return f"앞으로 {h}시간 안에 예정된 미리알림이 없습니다."
    lines = [_fmt_due(t, s) for _, t, s in items[:10]]
    return f"다가오는 미리알림 {len(items)}건: " + " / ".join(lines)


def calendar_text(hours: Any = 24, fetch=fetch_events) -> str:
    try:
        h = max(1, min(168, int(hours)))
    except (TypeError, ValueError):
        h = 24
    items = fetch(h * 3600)
    if not items:
        return f"앞으로 {h}시간 안에 캘린더 일정이 없습니다."
    lines = [_fmt_due(t, s) for _, t, s in items[:10]]
    return f"다가오는 일정 {len(items)}건: " + " / ".join(lines)
```

SDK 래퍼(`_battery` 근처에):

```python
@tool("get_reminders", "다가오는 미리알림 목록을 읽는다(읽기 전용).",
      {"type": "object", "properties": {"hours": {"type": "integer"}}})
async def _get_reminders(args):
    return _text(reminders_text((args or {}).get("hours", 24)))


@tool("get_calendar_events", "다가오는 캘린더 일정을 읽는다(읽기 전용).",
      {"type": "object", "properties": {"hours": {"type": "integer"}}})
async def _get_calendar_events(args):
    return _text(calendar_text((args or {}).get("hours", 24)))
```

`build_jarvis_mcp_server`의 `tools = [...]` 리스트에 `_get_reminders, _get_calendar_events` 추가, `JARVIS_TOOL_NAMES` 튜플에 `"get_reminders", "get_calendar_events"` 추가.

- [ ] **Step 4: 통과 확인** — `tests/tools/test_jarvis_mcp.py` 전체 PASS
- [ ] **Step 5: Commit** — `feat(tools): 미리알림/캘린더 읽기 도구 — 브리핑·일정 질문용`

---

### Task 8: ProactiveEngine

**Files:**
- Create: `jarvis/proactive/engine.py`
- Test: `tests/proactive/test_engine.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/proactive/test_engine.py
import asyncio

from jarvis.proactive.engine import ProactiveEngine
from jarvis.proactive.events import Announcement


class _Mon:
    interval_s = 0.01

    def __init__(self, batches):
        self._batches = list(batches)

    def poll(self):
        return self._batches.pop(0) if self._batches else []


def _ann(kind, prio, t, ttl=100.0, prompt=None):
    return Announcement(kind, prompt or kind, prio, t, t + ttl)


def _engine(monitors, *, can_speak=lambda: True, clock=None, cooldown_s=0.0):
    spoken = []
    t = {"v": 0.0} if clock is None else clock

    async def announce(prompt):
        spoken.append(prompt)

    eng = ProactiveEngine(monitors, announce=announce, can_speak=can_speak,
                          clock=lambda: t["v"], cooldown_s=cooldown_s, tick_s=0.01)
    return eng, spoken, t


def _run(eng, seconds=0.15):
    async def go():
        eng.start()
        await asyncio.sleep(seconds)
        eng.stop()

    asyncio.run(go())


def test_delivers_when_idle():
    eng, spoken, t = _engine([_Mon([[_ann("briefing", 2, 0.0)]])])
    _run(eng)
    assert spoken == ["briefing"]


def test_holds_while_busy_then_delivers():
    busy = {"v": True}
    eng, spoken, t = _engine([_Mon([[_ann("battery_low", 2, 0.0)]])],
                             can_speak=lambda: not busy["v"])

    async def go():
        eng.start()
        await asyncio.sleep(0.05)
        assert spoken == []          # 대화 중 보류
        busy["v"] = False
        await asyncio.sleep(0.05)
        eng.stop()

    asyncio.run(go())
    assert spoken == ["battery_low"]


def test_priority_order_and_expiry():
    anns = [_ann("greet_back", 4, 0.0), _ann("battery_critical", 0, 0.0),
            _ann("briefing", 2, 0.0, ttl=-1.0)]   # 브리핑은 이미 만료
    eng, spoken, t = _engine([_Mon([anns])])
    _run(eng)
    assert spoken[0] == "battery_critical"
    assert "briefing" not in spoken               # 만료 폐기


def test_kind_cooldown():
    eng, spoken, t = _engine(
        [_Mon([[_ann("battery_low", 2, 0.0)], [], [_ann("battery_low", 2, 0.0)]])],
        cooldown_s=999.0)
    _run(eng)
    assert spoken == ["battery_low"]              # 같은 kind 쿨다운


def test_briefing_supersedes_boot_greet():
    eng, spoken, t = _engine([_Mon([[_ann("briefing", 2, 0.0)]])],
                             can_speak=lambda: True)
    eng.enqueue(_ann("boot_greet", 3, 0.0))

    _run(eng)
    assert "boot_greet" not in spoken and "briefing" in spoken


def test_monitor_error_does_not_kill_engine():
    class _Boom:
        interval_s = 0.01

        def poll(self):
            raise RuntimeError("monitor bug")

    eng, spoken, t = _engine([_Boom(), _Mon([[_ann("greet_back", 4, 0.0)]])])
    _run(eng)
    assert spoken == ["greet_back"]               # 죽은 감시자 무시, 엔진 생존
```

- [ ] **Step 2: 실패 확인** — ModuleNotFoundError
- [ ] **Step 3: 구현**

```python
# jarvis/proactive/engine.py
"""능동 알림 엔진: 감시자 폴링 → 우선순위 큐 → IDLE일 때 두뇌로 전달.
감시자 하나의 예외는 그 감시자의 이번 폴링만 버린다(웨이크 루프와 같은 원칙).
전달 정책: 만료 폐기, kind별 쿨다운, briefing이 boot_greet를 대체."""
from __future__ import annotations

import asyncio
import time

from .events import Announcement


class ProactiveEngine:
    def __init__(self, monitors, *, announce, can_speak,
                 clock=time.monotonic, cooldown_s: float = 600.0,
                 tick_s: float = 1.0):
        self._monitors = list(monitors)
        self._announce = announce          # async (prompt) -> None
        self._can_speak = can_speak        # () -> bool
        self._clock = clock
        self._cooldown_s = cooldown_s
        self._tick_s = tick_s
        self._pending: list[Announcement] = []
        self._last_spoken: dict[str, float] = {}
        self._next_poll: dict[int, float] = {}
        self._task: asyncio.Task | None = None

    def enqueue(self, ann: Announcement) -> None:
        if ann.kind == "briefing":
            # 브리핑이 인사를 겸한다 — 대기 중인 부팅 인사는 무의미.
            self._pending = [a for a in self._pending if a.kind != "boot_greet"]
        if any(a.kind == ann.kind for a in self._pending):
            return                          # 같은 종류 중복 대기 금지
        self._pending.append(ann)

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop())

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _poll_due_monitors(self) -> None:
        now = self._clock()
        for idx, mon in enumerate(self._monitors):
            if now < self._next_poll.get(idx, 0.0):
                continue
            self._next_poll[idx] = now + getattr(mon, "interval_s", 60.0)
            try:
                anns = await asyncio.to_thread(mon.poll)
            except Exception as exc:  # noqa: BLE001 - 감시자 하나가 엔진을 죽이면 안 된다
                print(f"[능동] {type(mon).__name__} 폴링 오류(계속): {exc}")
                continue
            for a in anns:
                self.enqueue(a)

    def _pick(self) -> Announcement | None:
        now = self._clock()
        self._pending = [a for a in self._pending if not a.expired(now)]
        ready = [a for a in self._pending
                 if now - self._last_spoken.get(a.kind, -1e12) >= self._cooldown_s]
        if not ready:
            return None
        best = min(ready, key=lambda a: (a.priority, a.created_at))
        self._pending.remove(best)
        return best

    async def _loop(self) -> None:
        try:
            while True:
                await self._poll_due_monitors()
                if self._pending and self._can_speak():
                    ann = self._pick()
                    if ann is not None:
                        self._last_spoken[ann.kind] = self._clock()
                        try:
                            await self._announce(ann.prompt)
                        except Exception as exc:  # noqa: BLE001 - 한 건 실패가 엔진을 멈추면 안 된다
                            print(f"[능동] 알림 전달 오류(계속): {exc}")
                await asyncio.sleep(self._tick_s)
        except asyncio.CancelledError:
            pass
```

- [ ] **Step 4: 통과 확인** — 6 PASS
- [ ] **Step 5: Commit** — `feat(proactive): ProactiveEngine — 폴링/우선순위/쿨다운/만료/IDLE 보류`

---

### Task 9: 오케스트레이터 announce + 두뇌 지침

**Files:**
- Modify: `jarvis/core/orchestrator.py`
- Modify: `jarvis/brain/subscription.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: 실패하는 테스트 추가** — tests/test_orchestrator.py 끝에:

```python
def test_announce_speaks_without_ack_filler():
    # 사용자가 기다리는 게 아니므로 "잠시만요" 필러 없이 바로 본문만.
    orch, pb = _make()
    orch.wake = object()                  # follow-up 창 조건

    async def run():
        await orch.announce("배터리가 18%까지 떨어졌다")
        await orch._task
        return asyncio.get_running_loop().time() < orch._follow_up_until

    in_window = asyncio.run(run())
    assert len(pb.feeds) == 2             # 답변 두 문장만(필러 없음 — 기존 ack 포함 경로는 3+)
    assert orch.state == State.IDLE
    assert in_window                      # 알림 후에도 되묻기 창이 열린다


def test_announce_skipped_when_busy():
    orch, pb = _make()
    orch.state = State.SPEAKING

    async def run():
        await orch.announce("아무거나")
        assert orch._task is None

    asyncio.run(run())
    assert pb.feeds == []


def test_announce_error_recovers_to_idle():
    class _BoomBrain2:
        async def respond(self, user_text):
            raise RuntimeError("brain boom")
            yield  # pragma: no cover

    orch, _ = _make()
    orch.brain = _BoomBrain2()

    async def run():
        await orch.announce("이벤트")
        await orch._task

    asyncio.run(run())
    assert orch.state == State.IDLE
```

- [ ] **Step 2: 실패 확인** — AttributeError announce
- [ ] **Step 3: 구현**

3a. orchestrator.py — `_pipeline_text` 시그니처를 `async def _pipeline_text(self, text: str, *, ack: bool = True) -> None:`로 바꾸고 `await self._play_ack()` 줄을:

```python
        if ack:
            await self._play_ack()  # "One moment, sir." — 능동 알림은 생략(아무도 안 기다림)
```

3b. orchestrator.py — `_attentive_expiry` 아래에 추가:

```python
    # ----- 능동 알림 (ProactiveEngine이 호출) -----
    def _can_announce(self) -> bool:
        return (self.state == State.IDLE
                and (self._task is None or self._task.done()))

    async def announce(self, prompt: str) -> None:
        # 같은 루프에서 불린다. self._task로 돌려 PTT/웨이크가 평소처럼 끼어들 수 있게.
        if not self._can_announce():
            return
        self.state = State.THINKING
        self._task = asyncio.create_task(self._handle_announce(prompt))

    async def _handle_announce(self, prompt: str) -> None:
        try:
            await self._pipeline_text(f"[SYSTEM EVENT] {prompt}", ack=False)
        except Exception as exc:  # noqa: BLE001 - 알림 실패가 상태를 가두면 안 된다
            print(f"[능동] 처리 오류(IDLE 복귀): {exc}")
            self._to_idle()
```

3c. orchestrator.py — `__init__`에 `self.proactive = None` 추가(`self.wake = wake` 아래),
`run()`에서 `self.activator.start(...)` 직전에:

```python
        if self.proactive is not None:
            self.proactive.start()
```

3d. subscription.py — `_GUIDANCE_EN`의 `[KO]` 문장 바로 앞에 한 문장 추가:

```python
    "If the user message begins with '[SYSTEM EVENT]', nobody asked — you are "
    "proactively informing sir (battery, schedule, briefing, greeting): deliver it "
    "in one or two short witty sentences, never ask what he needs. For a briefing "
    "event, call the weather/reminders/calendar tools first, then summarise. "
```

`_GUIDANCE_KO`에도 대응 한 문장(같은 위치 규칙):

```python
    "사용자 메시지가 '[SYSTEM EVENT]'로 시작하면 누가 물은 게 아니라 네가 먼저 알리는 "
    "것이다(배터리·일정·브리핑·인사): 한두 문장으로 짧게 위트 있게 알리고, 뭘 도울지 "
    "되묻지 마라. "
```

(KO 지침 파일 구조를 먼저 READ해서 자연스러운 위치에 삽입.)

- [ ] **Step 4: 통과 확인** — `tests/test_orchestrator.py` 전체 + `tests/brain/test_subscription.py` PASS
- [ ] **Step 5: Commit** — `feat(proactive): announce 경로 — 필러 없는 능동 발화 + 시스템 이벤트 지침`

---

### Task 10: 배선 — __main__ 조립 + 부팅 인사

**Files:**
- Modify: `jarvis/__main__.py`
- Modify: `tests/test_main_wiring.py`

- [ ] **Step 1: 실패하는 테스트 추가** — tests/test_main_wiring.py 끝에:

```python
def test_build_orchestrator_wires_proactive():
    orch = _build()
    assert orch.proactive is not None
    assert any(type(m).__name__ == "BatteryMonitor" for m in orch.proactive._monitors)


def test_proactive_disabled_by_env(monkeypatch):
    monkeypatch.setenv("JARVIS_PROACTIVE_ENABLED", "false")
    orch = _build()
    assert orch.proactive is None
```

- [ ] **Step 2: 실패 확인** — AssertionError (proactive None)
- [ ] **Step 3: 구현** — __main__.py:

import 블록에:

```python
from .proactive.engine import ProactiveEngine
from .proactive.monitors import build_monitors
```

`build_orchestrator`의 `return Orchestrator(...)`를 변수로 받아서:

```python
    orch = Orchestrator(
        ...기존 인자 그대로...
    )
    if settings.proactive_enabled:
        orch.proactive = ProactiveEngine(
            build_monitors(settings),
            announce=orch.announce,
            can_speak=orch._can_announce,
            cooldown_s=settings.proactive_cooldown_min * 60,
        )
    return orch
```

`_amain`의 준비 완료 print 직후(orch.run() 호출 전)에 부팅 인사 적재:

```python
        if orch.proactive is not None:
            from time import monotonic

            from .proactive.events import Announcement
            now = monotonic()
            orch.proactive.enqueue(Announcement(
                "boot_greet", "자비스가 방금 기동했다 — 시스템 정상임을 짧게 보고하며 인사",
                3, now, now + 300))
```

(주의: 엔진 clock 기본값이 time.monotonic이므로 같은 시계 사용. SessionMonitor가
기동 시 화면 해제 상태에서 briefing을 내면 엔진 enqueue 규칙이 boot_greet를
대체한다 — 스펙의 이중 인사 방지.)

- [ ] **Step 4: 통과 확인** — `tests/test_main_wiring.py` 전체 PASS
- [ ] **Step 5: Commit** — `feat(proactive): 메인 배선 — 엔진 조립 + 부팅 인사`

---

### Task 11: 전체 검증 (라이브 재시작은 컨트롤러가)

- [ ] **Step 1:** `cd ~/jarvis && .venv/bin/python -m pytest -q` → 전부 PASS
- [ ] **Step 2:** `.venv/bin/ruff check jarvis tests` → clean
- [ ] **Step 3:** 라이브 재시작·수동 체크는 컨트롤러(메인 세션)가 수행:
  1. 재시작 → 부팅 인사 또는 (그날 첫 사용이면) 아침 브리핑이 나오는지
  2. 화면 잠갔다 풀기 → 인사/브리핑 규칙대로인지
  3. 미리알림을 7분 뒤로 하나 만들기 → 알림 오는지 (첫 호출 시 자동화 권한 팝업 허용)
  4. 알림 직후 "얼마나 남았어?" follow-up 되묻기
  5. 대화 중 알림이 끼어들지 않는지
- [ ] **Step 4:** 메모리 업데이트 + 잔여 커밋

---

## 셀프리뷰 결과

- **스펙 커버리지**: 이벤트 카탈로그 10종 — battery_critical/low(T4) ✓ charger_on/charge_full(T4) ✓ briefing/greet_back(T5, 기동 시 해제=첫 해제 규칙 포함) ✓ late_night(T5, 기본 off는 T6 build_monitors) ✓ reminder_due/event_soon(T6) ✓ boot_greet(T10, briefing 대체 규칙은 T8 enqueue) ✓. 전달 정책(IDLE 보류/우선순위/만료/쿨다운/필러 생략/attentive 유지) = T8+T9 ✓. 새 MCP 도구 = T7 ✓. 설정 8종 = T2 ✓. 감시자 실패 격리 = T8 `_poll_due_monitors` ✓. 권한 팝업 문서화 = T3 Step4 ✓.
- **타입 일치**: `Announcement(kind, prompt, priority, created_at, expires_at)` 시그니처 T1↔T4/T5/T6/T8/T10 ✓. `announce(prompt)`/`_can_announce` T9↔T8(`announce=`, `can_speak=`)·T10 ✓. `fetch(window_s, runner=...)` 계약 T3↔T6/T7(테스트 람다가 `w, runner=None` 시그니처로 맞춤) ✓. `interval_s` 속성 T4/T5/T6↔T8 `getattr(mon, "interval_s", 60.0)` ✓.
- **플레이스홀더 없음**: 모든 스텝 완결 코드. AppleScript만 "환경 적응 재량 + 출력 계약 고정"으로 명시(실기기 의존이라 의도적).
