from jarvis.__main__ import build_orchestrator
from jarvis.core.orchestrator import Orchestrator


class _FakeAnthropic:
    class _M:
        def stream(self, **k):  # pragma: no cover - not called in wiring test
            raise AssertionError

        async def create(self, **k):  # pragma: no cover
            raise AssertionError

    def __init__(self):
        self.messages = self._M()


def test_build_orchestrator_wires_all_components():
    orch = build_orchestrator(client=_FakeAnthropic())
    assert isinstance(orch, Orchestrator)
    assert orch.stt is not None
    assert orch.brain is not None
    assert orch.tts.sample_rate > 0
    assert orch.vc is not None
    assert orch.playback.sample_rate == 48000
    assert orch.activator is not None
    assert orch.capture is not None
