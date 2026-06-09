import numpy as np

from jarvis.audio.capture import MicCapture


def test_callback_accumulates_mono_float32():
    cap = MicCapture(sample_rate=16000)
    cap._frames = []
    cap._callback(np.full((4, 1), 0.5, dtype=np.float32), 4, None, None)
    cap._callback(np.full((2, 1), -0.5, dtype=np.float32), 2, None, None)
    pcm = cap._drain()
    assert pcm.dtype == np.float32
    assert pcm.ndim == 1
    assert pcm.shape == (6,)
    assert np.allclose(pcm[:4], 0.5) and np.allclose(pcm[4:], -0.5)


def test_drain_empty_returns_zero_length():
    cap = MicCapture()
    cap._frames = []
    out = cap._drain()
    assert out.dtype == np.float32 and out.shape == (0,)
