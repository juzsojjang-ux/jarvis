from jarvis.core.control_gate import CONTROL_GATE, ControlGate


def test_gate_off_by_default():
    g = ControlGate(clock=lambda: 100.0)
    assert g.is_on() is False


def test_enable_holds_until_ttl_then_expires():
    t = [100.0]
    g = ControlGate(clock=lambda: t[0])
    g.enable(300.0)
    assert g.is_on() is True
    t[0] = 399.9
    assert g.is_on() is True
    t[0] = 400.0
    assert g.is_on() is False


def test_disable_turns_off_immediately():
    t = [100.0]
    g = ControlGate(clock=lambda: t[0])
    g.enable(300.0)
    g.disable()
    assert g.is_on() is False


def test_reenable_extends_window():
    t = [100.0]
    g = ControlGate(clock=lambda: t[0])
    g.enable(300.0)
    t[0] = 350.0
    g.enable(300.0)  # 다시 켜면 새 창
    t[0] = 600.0
    assert g.is_on() is True


def test_module_singleton_exists():
    assert isinstance(CONTROL_GATE, ControlGate)
    assert CONTROL_GATE.is_on() is False  # 실시간 시계 — 기본은 꺼짐
