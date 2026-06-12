import asyncio

from jarvis.__main__ import build_orchestrator
from jarvis.brain.subscription import SubscriptionBrain
from jarvis.core.orchestrator import Orchestrator


class _FakeAnthropic:
    class _M:
        def stream(self, **k):  # pragma: no cover - not called in wiring test
            raise AssertionError

        async def create(self, **k):  # pragma: no cover
            raise AssertionError

    def __init__(self):
        self.messages = self._M()


def _build():
    return asyncio.run(build_orchestrator(client=_FakeAnthropic()))


def _build_api(monkeypatch):
    # Force the Anthropic-API brain so its registry/confirm wiring is observable.
    monkeypatch.setenv("JARVIS_BRAIN_BACKEND", "api")
    return asyncio.run(build_orchestrator(client=_FakeAnthropic()))


def test_build_orchestrator_wires_all_components():
    orch = _build()
    assert isinstance(orch, Orchestrator)
    assert orch.stt is not None
    assert orch.brain is not None
    assert orch.tts.sample_rate > 0
    assert orch.vc is not None
    assert orch.playback.sample_rate == 48000
    assert orch.activator is not None
    assert orch.capture is not None
    assert orch.hud is not None  # HUD orb server wired by default


def test_default_brain_is_subscription():
    # No API key required by default — the brain runs on the Claude subscription login.
    assert isinstance(_build().brain, SubscriptionBrain)


def test_build_orchestrator_registers_builtin_tools(monkeypatch):
    orch = _build_api(monkeypatch)
    names = {d.get("name") for d in orch.brain._registry.tools()}
    assert {"get_time", "get_weather", "web_search", "remember", "calc",
            "voice_status"} <= names


def test_build_orchestrator_injects_voice_confirm(monkeypatch):
    orch = _build_api(monkeypatch)
    assert callable(orch.brain._confirm)


def test_build_orchestrator_wires_micstream_and_wake():
    from pathlib import Path
    orch = _build()
    assert orch.micstream is not None
    assert orch.capture._mic is orch.micstream     # 캡처가 같은 스트림을 공유
    if Path("~/jarvis/voice_models/silero_vad.onnx").expanduser().exists():
        assert orch.wake is not None               # 모델이 있으면 웨이크 가동


def test_wake_disabled_by_env(monkeypatch):
    monkeypatch.setenv("JARVIS_WAKE_ENABLED", "false")
    orch = _build()
    assert orch.wake is None


def test_build_orchestrator_wires_proactive():
    import sys
    orch = _build()
    assert orch.proactive is not None
    kinds = [type(m).__name__ for m in orch.proactive._monitors]
    if sys.platform == "darwin":
        assert "BatteryMonitor" in kinds
    else:  # 맥 전용 감시자는 다른 OS에서 안 만들어진다(윈도우 Quartz 스팸 수정)
        assert "BatteryMonitor" not in kinds and "SessionMonitor" not in kinds


def test_proactive_disabled_by_env(monkeypatch):
    monkeypatch.setenv("JARVIS_PROACTIVE_ENABLED", "false")
    orch = _build()
    assert orch.proactive is None


def test_build_orchestrator_wires_timer_monitor():
    orch = _build()
    names = [type(m).__name__ for m in orch.proactive._monitors]
    assert "TimerMonitor" in names
    # 타이머는 연속 알림이 정상 — 쿨다운 면제 확인
    assert orch.proactive._cooldown_overrides.get("timer_done") == 0.0
