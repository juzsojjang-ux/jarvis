from datetime import date, datetime
from types import SimpleNamespace

from jarvis.proactive.monitors import (
    BatteryMonitor,
    CalendarMonitor,
    LateNightMonitor,
    RemindersMonitor,
    SessionMonitor,
    TimerMonitor,
    build_monitors,
    PsutilBatteryMonitor, MorningBriefingMonitor, MailMonitor, SelfCheckMonitor,
)
from jarvis.proactive.timers import TimerBoard


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
    out = mon.poll()                              # 첫 폴링: 이미 20% 아래 → 즉시 경고
    assert [a.kind for a in out] == ["battery_low"]
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


def test_boot_below_threshold_warns_immediately():
    mon = BatteryMonitor(levels=[20, 10, 5])
    mon._runner = _pmset_runner(_batt(4))
    out = mon.poll()
    kinds = [a.kind for a in out]
    assert "battery_critical" in kinds            # 4%로 부팅해도 침묵하지 않는다


# ---------------------------------------------------------------------------
# SessionMonitor / LateNightMonitor 테스트
# ---------------------------------------------------------------------------

class _FakeSession:
    """locked_fn/clock/today_fn 주입으로 시나리오 재현."""

    def __init__(self):
        self.locked = False
        self.t = 1000.0
        self.day = date(2026, 6, 10)


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
    fs.locked = True
    mon.poll()
    fs.t += 5 * 3600                               # 쿨다운(4h) 경과
    fs.locked = False
    assert [a.kind for a in mon.poll()] == ["greet_back"]
    fs.locked = True
    mon.poll()
    fs.t += 600                                    # 쿨다운 미경과
    fs.locked = False
    assert mon.poll() == []


def test_new_day_briefs_again():
    fs = _FakeSession()
    mon = _session_mon(fs)
    mon.poll()                                     # 오늘 브리핑 소모
    fs.locked = True
    mon.poll()
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


def test_late_night_quiet_outside_window():
    fs = _FakeSession()
    mon = LateNightMonitor(locked_fn=lambda: fs.locked, clock=lambda: fs.t,
                           now_fn=lambda: datetime(2026, 6, 11, 23, 30),
                           today_fn=lambda: fs.day)
    assert mon.poll() == []


# ---------------------------------------------------------------------------
# RemindersMonitor / CalendarMonitor / build_monitors 테스트
# ---------------------------------------------------------------------------

def test_reminder_due_within_lead_announced_once():
    items = {"v": [("id-1", "회의 자료", 540)]}        # 9분 후 due
    mon = RemindersMonitor(lead_s=600, fetch=lambda w, runner=None: items["v"])
    out = mon.poll()
    assert len(out) == 1 and out[0].kind == "reminder_due" and "회의 자료" in out[0].prompt
    assert mon.poll() == []                            # 같은 id 재알림 금지
    items["v"] = [("id-1", "회의 자료", 400), ("id-2", "약", 7200)]
    assert mon.poll() == []                            # id-2는 lead 밖


def test_reminder_set_prunes_vanished_ids():
    items = {"v": [("id-1", "회의 자료", 540)]}
    mon = RemindersMonitor(lead_s=600, fetch=lambda w, runner=None: items["v"])
    mon.poll()                                         # id-1 알림 소모
    items["v"] = []                                    # 완료/삭제되어 사라짐
    mon.poll()
    items["v"] = [("id-1", "회의 자료", 300)]           # 같은 id가 재등장(새 due)
    assert len(mon.poll()) == 1                        # 다시 알릴 수 있어야 한다


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

    kinds = [type(m).__name__ for m in build_monitors(_S(), platform="darwin")]
    assert "LateNightMonitor" not in kinds
    assert {"BatteryMonitor", "SessionMonitor", "RemindersMonitor",
            "CalendarMonitor"} <= set(kinds)
    _S.proactive_late_night = True
    kinds = [type(m).__name__ for m in build_monitors(_S(), platform="darwin")]
    assert "LateNightMonitor" in kinds


# ---------------------------------------------------------------------------
# TimerMonitor 테스트
# ---------------------------------------------------------------------------

def test_timer_monitor_announces_due_once():
    t = {"v": 0.0}
    board = TimerBoard(clock=lambda: t["v"])
    mon = TimerMonitor(board, clock=lambda: t["v"])
    board.add(5, "달걀")
    assert mon.poll() == []
    t["v"] = 6.0
    out = mon.poll()
    assert len(out) == 1 and out[0].kind == "timer_done" and "달걀" in out[0].prompt
    assert out[0].priority == 1 and out[0].expires_at == 6.0 + 120
    assert mon.poll() == []


def test_build_monitors_includes_timer_when_board_given():
    class _S:
        battery_warn_levels = [20, 10, 5]
        reminder_lead_min = 10
        event_lead_min = 10
        greet_cooldown_h = 4.0
        briefing_expire_h = 2.0
        proactive_late_night = False

    kinds = [type(m).__name__ for m in build_monitors(_S(), platform="darwin")]
    assert "TimerMonitor" not in kinds
    kinds = [type(m).__name__ for m in build_monitors(_S(), timers=TimerBoard(), platform="darwin")]
    assert "TimerMonitor" in kinds


def test_build_monitors_skips_mac_monitors_on_windows():
    """윈도우에선 Quartz/pmset/osascript 감시자를 아예 안 만든다(폴링 스팸 방지)."""
    class _S:
        battery_warn_levels = (20, 10, 5)
        greet_cooldown_h = 4
        briefing_expire_h = 2
        reminder_lead_min = 10
        event_lead_min = 15
        proactive_late_night = False
    kinds = [type(m).__name__ for m in build_monitors(_S(), platform="win32")]
    assert "SessionMonitor" not in kinds and "BatteryMonitor" not in kinds


# ----- 4단계 능동성 확장: 새 감시자들 -----

def test_psutil_battery_warns_on_threshold_cross():
    reads = iter([(25, False), (18, False), (18, False)])
    m = PsutilBatteryMonitor(reader=lambda: next(reads), clock=lambda: 100.0)
    assert m.poll() == []                       # 25% — 아직
    out = m.poll()
    assert len(out) == 1 and out[0].kind == "battery_low" and "18%" in out[0].prompt
    assert m.poll() == []                       # 같은 문턱 반복 경고 금지


def test_psutil_battery_charger_on_transition():
    reads = iter([(50, False), (50, True)])
    m = PsutilBatteryMonitor(reader=lambda: next(reads), clock=lambda: 100.0)
    m.poll()
    out = m.poll()
    assert [a.kind for a in out] == ["charger_on"]


def test_morning_briefing_once_per_day():
    from datetime import datetime as dt, date as d
    today = {"v": d(2026, 6, 12)}
    now = {"v": dt(2026, 6, 12, 7, 0)}
    m = MorningBriefingMonitor(hour=8, clock=lambda: 0.0,
                               now_fn=lambda: now["v"], today_fn=lambda: today["v"])
    assert m.poll() == []                       # 8시 전
    now["v"] = dt(2026, 6, 12, 8, 1)
    out = m.poll()
    assert len(out) == 1 and out[0].kind == "briefing"
    assert m.poll() == []                       # 같은 날 중복 금지
    today["v"] = d(2026, 6, 13); now["v"] = dt(2026, 6, 13, 9, 0)
    assert len(m.poll()) == 1                   # 다음날 다시


def test_mail_monitor_announces_only_increase():
    class _R:
        def __init__(self): self.vals = iter(["3", "3", "5", "4"])
        def __call__(self, *a, **k):
            class R: pass
            r = R(); r.stdout = next(self.vals); return r
    m = MailMonitor(runner=_R(), clock=lambda: 50.0)
    assert m.poll() == []                       # 기준선
    assert m.poll() == []                       # 변화 없음
    out = m.poll()
    assert len(out) == 1 and out[0].kind == "new_mail" and "2통" in out[0].prompt
    assert m.poll() == []                       # 줄어든 건 알림 아님


def test_mail_monitor_survives_runner_failure():
    def boom(*a, **k):
        raise RuntimeError("mail app closed")
    m = MailMonitor(runner=boom, clock=lambda: 0.0)
    assert m.poll() == []


def test_selfcheck_monitor_reports_only_new_failures():
    from jarvis.core.selfcheck import Check
    state = {"checks": [Check("두뇌", True, "ok"), Check("마이크", True, "ok")]}
    m = SelfCheckMonitor(checker=lambda: state["checks"], clock=lambda: 10.0)
    assert m.poll() == []                       # 전부 정상
    state["checks"] = [Check("두뇌", False, "연결 끊김"), Check("마이크", True, "ok")]
    out = m.poll()
    assert len(out) == 1 and "두뇌" in out[0].prompt
    assert m.poll() == []                       # 같은 이상 반복 보고 금지
    state["checks"] = [Check("두뇌", False, "연결 끊김"), Check("마이크", False, "장치 없음")]
    out = m.poll()
    assert len(out) == 1 and "마이크" in out[0].prompt and "두뇌" not in out[0].prompt
