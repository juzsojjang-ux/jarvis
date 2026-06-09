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
