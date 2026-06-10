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
