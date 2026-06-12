import asyncio

import numpy as np

import sys

import pytest

from jarvis.tts.system_say import SystemSayTTS

pytestmark = pytest.mark.skipif(sys.platform != "darwin",
                                reason="macOS `say` 명령 전용 백엔드")


def test_synth_returns_mono_float32_in_range():
    tts = SystemSayTTS(voice="Yuna")
    tts.warm()
    pcm = asyncio.run(tts.synth("안녕하세요"))
    assert pcm.dtype == np.float32
    assert pcm.ndim == 1
    assert len(pcm) > 0
    assert float(np.max(np.abs(pcm))) <= 1.0
    assert tts.sample_rate > 0
