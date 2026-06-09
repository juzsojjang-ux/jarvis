import numpy as np

from jarvis.audio.util import resample


def test_identity_when_rates_equal():
    x = np.ones(100, dtype=np.float32)
    out = resample(x, 16000, 16000)
    assert out.dtype == np.float32
    assert np.array_equal(out, x)


def test_upsample_length_and_dtype():
    x = np.ones(16000, dtype=np.float32)
    out = resample(x, 16000, 48000)
    assert out.dtype == np.float32
    assert abs(len(out) - 48000) <= 2


def test_accepts_non_float_input():
    x = np.ones(8000, dtype=np.int16)
    out = resample(x, 8000, 16000)
    assert out.dtype == np.float32
    assert abs(len(out) - 16000) <= 2
