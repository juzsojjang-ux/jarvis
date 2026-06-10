import asyncio
import sys
from pathlib import Path

import numpy as np

from jarvis.tts.pocket_tts import PocketTTS

# Reuse the hermetic ipc fake worker (0.1s sine @ 44100) — PocketTTS inherits the
# MeloTTSKR proc/warm/synth plumbing, so this exercises the IPC path with no pocket-tts.
FAKE = str(Path(__file__).parent / "fake_worker.py")


def test_default_sample_rate_is_24000():
    assert PocketTTS.sample_rate == 24000


def test_env_carries_reference():
    tts = PocketTTS(worker_cmd=[sys.executable, FAKE], ref_path="/tmp/jref.wav")
    assert tts._env["JARVIS_POCKET_REF"] == "/tmp/jref.wav"
    assert tts._env["PYTHONPATH"]  # two-venv isolation


def test_warm_and_synth_over_subprocess():
    tts = PocketTTS(worker_cmd=[sys.executable, FAKE])
    tts.warm()
    try:
        pcm = asyncio.run(tts.synth("Good evening, sir."))
        assert isinstance(pcm, np.ndarray) and pcm.dtype == np.float32
        assert pcm.shape[0] == int(0.1 * 44100)  # fake worker's sine
    finally:
        tts.close()
