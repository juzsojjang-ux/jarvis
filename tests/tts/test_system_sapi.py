"""윈도우 SAPI 폴백 — 디코더는 플랫폼 무관이라 여기서, 실제 PowerShell 합성은
윈도우에서만(아래 guard)."""
import sys

import numpy as np
import pytest

from jarvis.tts.system_sapi import SystemSapiTTS, _pcm_to_mono_float32


def test_decode_16bit_mono():
    pcm = np.array([0, 16384, -16384, 32767], dtype="<i2").tobytes()
    out = _pcm_to_mono_float32(pcm, channels=1, sampwidth=2)
    assert out.dtype == np.float32 and out.ndim == 1 and len(out) == 4
    assert abs(out[1] - 0.5) < 1e-3 and abs(out[2] + 0.5) < 1e-3


def test_decode_16bit_stereo_downmix():
    stereo = np.array([[10000, -10000], [20000, -20000]], dtype="<i2").tobytes()
    out = _pcm_to_mono_float32(stereo, channels=2, sampwidth=2)
    assert out.ndim == 1 and len(out) == 2
    assert abs(out[0]) < 1e-6 and abs(out[1]) < 1e-6  # L+R 평균 = 0


def test_decode_8bit_unsigned():
    raw = bytes([128, 255, 0, 192])  # 0점=128
    out = _pcm_to_mono_float32(raw, channels=1, sampwidth=1)
    assert abs(out[0]) < 1e-6 and out[1] > 0.9 and out[2] < -0.9


def test_decode_unexpected_width_returns_empty():
    assert len(_pcm_to_mono_float32(b"\x00\x00\x00\x00", channels=1, sampwidth=4)) == 0


def test_empty_text_returns_empty():
    # 빈 텍스트는 PowerShell 호출 없이 즉시 빈 배열(어떤 플랫폼이든).
    out = SystemSapiTTS()._synth("   ")
    assert out.dtype == np.float32 and len(out) == 0


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="SAPI는 윈도우 전용")
def test_sapi_synthesizes_on_windows():
    import asyncio
    out = asyncio.run(SystemSapiTTS().synth("Hello sir."))
    assert out.dtype == np.float32 and len(out) > 0
