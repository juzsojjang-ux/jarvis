from jarvis.core.control_gate import TRUST_GATE, TrustGate


def test_off_by_default():
    assert TrustGate(clock=lambda: 100.0).is_on() is False


def test_enable_until_ttl():
    t = [100.0]
    g = TrustGate(clock=lambda: t[0])
    g.enable(600.0)
    assert g.is_on() is True
    t[0] = 699.9
    assert g.is_on() is True
    t[0] = 700.0
    assert g.is_on() is False


def test_disable_immediate():
    t = [100.0]
    g = TrustGate(clock=lambda: t[0])
    g.enable(600.0)
    g.disable()
    assert g.is_on() is False


def test_singleton():
    assert isinstance(TRUST_GATE, TrustGate)
    assert TRUST_GATE.is_on() is False
