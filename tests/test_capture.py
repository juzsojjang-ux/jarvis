# tests/test_capture.py
import numpy as np

from jarvis.audio.capture import MicCapture
from jarvis.audio.micstream import MicStream


def _cap():
    ms = MicStream()
    cap = MicCapture(ms)
    return ms, cap


def test_chunks_accumulate_only_while_active():
    ms, cap = _cap()
    ms._callback(np.full((4, 1), 0.9, dtype=np.float32), 4, None, None)  # start 전
    cap.start()
    ms._callback(np.full((4, 1), 0.5, dtype=np.float32), 4, None, None)
    ms._callback(np.full((2, 1), -0.5, dtype=np.float32), 2, None, None)
    pcm = cap.stop()
    assert pcm.dtype == np.float32 and pcm.ndim == 1 and pcm.shape == (6,)
    assert np.allclose(pcm[:4], 0.5) and np.allclose(pcm[4:], -0.5)


def test_stop_without_audio_returns_zero_length():
    _, cap = _cap()
    cap.start()
    out = cap.stop()
    assert out.dtype == np.float32 and out.shape == (0,)


def test_chunks_after_stop_are_ignored():
    ms, cap = _cap()
    cap.start()
    cap.stop()
    ms._callback(np.full((4, 1), 0.5, dtype=np.float32), 4, None, None)
    assert len(cap._frames) == 0     # stop 후 콜백은 무시(두 번째 start의 clear에 가려지면 안 됨)
    cap.start()
    assert cap.stop().shape == (0,)


def test_sample_rate_mirrors_stream():
    ms, cap = _cap()
    assert cap.sample_rate == ms.sample_rate == 16000
