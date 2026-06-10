"""End-to-end drop-in proof: once a JARVIS model is present, the factory builds a
PersistentRVC and the orchestrator's _speak path flows tts -> RVC convert -> resample
-> playback (+ orb levels queued). The neural runtime is stubbed by a fake persistent
worker honoring the line protocol, so this verifies the WHOLE wiring the user relies on.
"""
import asyncio
import sys
import types

import numpy as np

from jarvis.core.orchestrator import Orchestrator
from jarvis.vc.factory import make_vc
from jarvis.vc.rvc_persistent import PersistentRVC

# Fake persistent worker: READY, then 0.2s 220Hz sine per CONVERT request.
FAKE_WORKER = (
    "import sys, numpy as np, soundfile as sf\n"
    "print('READY', flush=True)\n"
    "for line in sys.stdin:\n"
    "    parts = line.rstrip('\\n').split('\\t')\n"
    "    sr = 40000\n"
    "    t = np.arange(int(0.2 * sr)) / sr\n"
    "    sf.write(parts[2], (0.1 * np.sin(2*np.pi*220*t)).astype('float32'), sr)\n"
    "    print('OK', flush=True)\n"
)


class FakeTTS:
    sample_rate = 44100

    async def synth(self, text):
        return np.zeros(int(0.1 * self.sample_rate), dtype=np.float32)


class FakePlayback:
    def __init__(self):
        self.fed = []

    def feed(self, pcm):
        self.fed.append(np.asarray(pcm))


def _orch(vc, playback):
    stub = types.SimpleNamespace()
    return Orchestrator(
        settings=types.SimpleNamespace(playback_rate=48000, language="ko"),
        activator=stub, capture=stub, stt=stub, brain=stub, chunker=stub,
        tts=FakeTTS(), vc=vc, playback=playback)


def test_factory_auto_builds_rvc_and_speak_flows(tmp_path):
    # 1) drop a fake model -> auto-detect builds the persistent RVC conversion
    pth = tmp_path / "jarvis.pth"
    pth.write_bytes(b"x")
    fake_worker = tmp_path / "fake_worker.py"
    fake_worker.write_text(FAKE_WORKER)
    settings = types.SimpleNamespace(
        vc_backend="auto", rvc_python=str(sys.executable),
        rvc_model_path=str(pth), rvc_index_path=str(tmp_path / "jarvis.index"),
        rvc_sample_rate=40000, rvc_index_rate=0.75, rvc_f0_up=0)
    vc = make_vc(settings)
    assert isinstance(vc, PersistentRVC)

    # 2) point at the fake worker (bypass .venv-rvc) and speak through the pipeline
    vc._cmd = [sys.executable, str(fake_worker)]
    playback = FakePlayback()
    orch = _orch(vc, playback)

    async def run():
        await orch._speak("자비스, 들리나?")
        # speaking levels were queued for the orb pump (one per 0.1s hop of 0.2s audio)
        assert orch._spk_levels.qsize() + (0 if orch._spk_pump is None else 1) >= 1
        if orch._spk_pump is not None:
            orch._spk_pump.cancel()
    asyncio.run(run())
    vc.close()

    assert len(playback.fed) == 1
    out = playback.fed[0]
    assert out.dtype == np.float32
    # fake emits 0.2s @ 40000 -> resampled to playback 48000
    assert abs(out.shape[0] - int(0.2 * 48000)) <= 128
