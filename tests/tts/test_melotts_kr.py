import asyncio
import sys
from pathlib import Path

import numpy as np

from jarvis.tts.melotts_kr import MeloTTSKR

FAKE = str(Path(__file__).parent / "fake_worker.py")


def test_warm_and_synth_over_subprocess():
    tts = MeloTTSKR(worker_cmd=[sys.executable, FAKE])
    tts.warm()
    try:
        pcm = asyncio.run(tts.synth("안녕"))
        assert isinstance(pcm, np.ndarray) and pcm.dtype == np.float32
        assert pcm.shape[0] == int(0.1 * 44100)
        pcm2 = asyncio.run(tts.synth("또"))   # reuses the same persistent worker
        assert pcm2.shape == pcm.shape
    finally:
        tts.close()


def test_sample_rate_is_44100():
    assert MeloTTSKR.sample_rate == 44100
