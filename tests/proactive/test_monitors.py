from datetime import date, datetime
from types import SimpleNamespace

from jarvis.proactive.monitors import BatteryMonitor, LateNightMonitor, SessionMonitor


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
