# tests/test_capture.py
import numpy as np

from jarvis.audio.capture import MicCapture
from jarvis.audio.micstream import MicStream


class _NoDevMicStream(MicStream):
    """실제 장치 금지 — capture.start()가 이제 닫힌 스트림을 여는(start) 의미라,
    테스트에서 진짜 MicStream을 쓰면 마이크가 열리고 종료 시 SIGSEGV가 난다."""

    def _open(self) -> None:
        self.opened = getattr(self, "opened", 0) + 1  # 열기 '시도'만 기록


def _cap():
    ms = _NoDevMicStream()
    cap = MicCapture(ms)
    return ms, cap


def test_start_requests_stream_open():
    ms, cap = _cap()
    cap.start()
    assert getattr(ms, "opened", 0) == 1  # PTT 전용 모드·음성확인이 여기에 의존한다


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
