"""End-to-end drop-in proof: once a JARVIS model is present, the factory builds an
RVCConversion and the orchestrator's _speak path flows tts -> RVC convert -> resample
-> playback. The neural runtime is stubbed by a fake CLI honoring our convert-contract,
so this verifies the WHOLE wiring the user relies on (only the real .pth is missing).
"""
import asyncio
import sys
import types

import numpy as np

from jarvis.core.orchestrator import Orchestrator
from jarvis.vc.factory import make_vc
from jarvis.vc.rvc import RVCConversion

# Fake RVC runtime: reads our `convert <in> <out> --model ...` contract, emits 0.2s.
FAKE_RVC = (
    "import sys, numpy as np, soundfile as sf\n"
    "out_wav = sys.argv[3]\n"
    "sr = 40000\n"
    "t = np.arange(int(0.2 * sr)) / sr\n"
    "sf.write(out_wav, (0.1 * np.sin(2*np.pi*220*t)).astype('float32'), sr)\n"
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
    # 1) drop a fake model -> auto-detect builds RVCConversion (runtime = this python)
    pth = tmp_path / "jarvis.pth"
    pth.write_bytes(b"x")
    fake_cli = tmp_path / "fake_rvc.py"
    fake_cli.write_text(FAKE_RVC)
    settings = types.SimpleNamespace(
        vc_backend="auto", rvc_python=str(sys.executable),
        rvc_model_path=str(pth), rvc_index_path=str(tmp_path / "jarvis.index"),
        rvc_sample_rate=40000, rvc_index_rate=0.75, rvc_f0_up=0)
    vc = make_vc(settings)
    assert isinstance(vc, RVCConversion)

    # 2) point the conversion at the fake runtime (bypass the .venv-rvc shim) and speak
    vc._rvc_cmd = [sys.executable, str(fake_cli)]
    playback = FakePlayback()
    orch = _orch(vc, playback)
    asyncio.run(orch._speak("자비스, 들리나?"))

    assert len(playback.fed) == 1
    out = playback.fed[0]
    assert out.dtype == np.float32
    # fake emits 0.2s @ 40000 -> resampled to playback 48000
    assert abs(out.shape[0] - int(0.2 * 48000)) <= 128
