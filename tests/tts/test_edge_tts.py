import asyncio
import io

import numpy as np
import soundfile as sf

from jarvis.tts.edge_tts_backend import EdgeTTS


def _wav_bytes(sr=24000, secs=0.1, freq=440):
    t = np.linspace(0, secs, int(sr * secs), endpoint=False)
    tone = (0.2 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    buf = io.BytesIO()
    sf.write(buf, tone, sr, format="WAV", subtype="FLOAT")
    return buf.getvalue()


def test_synth_decodes_to_mono_float32():
    wav = _wav_bytes()

    async def fake_fetch(text, voice):
        return wav

    tts = EdgeTTS(fetch=fake_fetch)
    out = asyncio.run(tts.synth("hello"))
    assert out.dtype == np.float32 and out.ndim == 1 and len(out) > 0
    assert tts.sample_rate == 24000


def test_empty_text_returns_empty():
    tts = EdgeTTS(fetch=None)
    out = asyncio.run(tts.synth("   "))
    assert out.dtype == np.float32 and len(out) == 0


def test_fetch_failure_returns_silence_not_raise():
    async def boom(text, voice):
        raise RuntimeError("network down")

    tts = EdgeTTS(fetch=boom)
    out = asyncio.run(tts.synth("hi"))
    assert len(out) == 0  # 무음, 예외 없음


def test_stereo_downmixed_to_mono():
    sr = 24000
    stereo = (np.random.rand(2400, 2) * 0.1).astype(np.float32)
    buf = io.BytesIO()
    sf.write(buf, stereo, sr, format="WAV", subtype="FLOAT")
    wav = buf.getvalue()

    async def fake_fetch(text, voice):
        return wav

    out = asyncio.run(EdgeTTS(fetch=fake_fetch).synth("x"))
    assert out.ndim == 1
