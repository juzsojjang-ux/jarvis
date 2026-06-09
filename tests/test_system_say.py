import asyncio

import numpy as np

from jarvis.tts.system_say import SystemSayTTS


def test_synth_returns_mono_float32_in_range():
    tts = SystemSayTTS(voice="Yuna")
    tts.warm()
    pcm = asyncio.run(tts.synth("안녕하세요"))
    assert pcm.dtype == np.float32
    assert pcm.ndim == 1
    assert len(pcm) > 0
    assert float(np.max(np.abs(pcm))) <= 1.0
    assert tts.sample_rate > 0
