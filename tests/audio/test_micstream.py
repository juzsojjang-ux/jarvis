import numpy as np

from jarvis.audio.micstream import MicStream


def _chunk(v=0.5, n=512):
    return np.full((n, 1), v, dtype=np.float32)


def test_callback_fans_out_flattened_copies():
    ms = MicStream()
    got_a, got_b = [], []
    ms.subscribe(got_a.append)
    ms.subscribe(got_b.append)
    ms._callback(_chunk(), 512, None, None)
    assert len(got_a) == 1 and len(got_b) == 1
    assert got_a[0].ndim == 1 and got_a[0].dtype == np.float32
    assert np.allclose(got_a[0], 0.5)


def test_unsubscribe_stops_delivery():
    ms = MicStream()
    got = []
    ms.subscribe(got.append)
    ms.unsubscribe(got.append)
    ms._callback(_chunk(), 512, None, None)
    assert got == []


def test_bad_subscriber_does_not_break_others():
    ms = MicStream()
    got = []

    def boom(chunk):
        raise RuntimeError("consumer bug")

    ms.subscribe(boom)
    ms.subscribe(got.append)
    ms._callback(_chunk(), 512, None, None)
    assert len(got) == 1


def test_double_subscribe_is_idempotent():
    ms = MicStream()
    got = []
    ms.subscribe(got.append)
    ms.subscribe(got.append)
    ms._callback(_chunk(), 512, None, None)
    assert len(got) == 1


def test_ensure_running_is_noop_before_start():
    ms = MicStream()
    ms.ensure_running()                      # start() 전엔 실제 장치를 열면 안 된다
    assert ms._stream is None


def test_ensure_running_is_noop_after_stop():
    ms = MicStream()
    ms._want_running = True          # start()를 흉내(실장치 금지) 후 stop으로 해제
    ms.stop()
    ms.ensure_running()
    assert ms._stream is None


class _ZombieStream:
    """macOS 함정 재현: 장치가 빠져도 active=True인데 콜백만 끊긴 스트림."""

    active = True

    def stop(self):
        pass

    def close(self):
        pass


def test_callback_records_liveness_timestamp():
    ms = MicStream()
    assert ms._last_chunk_t == 0.0
    ms._callback(_chunk(), 512, None, None)
    assert ms._last_chunk_t > 0.0


def test_ensure_running_reopens_zombie_stream(monkeypatch):
    # active=True지만 콜백이 2초 넘게 끊긴 스트림은 좀비로 보고 재생성해야 한다.
    ms = MicStream()
    opened = []
    monkeypatch.setattr(ms, "_open", lambda: opened.append(1))
    ms._want_running = True
    ms._stream = _ZombieStream()
    ms._last_chunk_t = 0.0                   # 콜백이 아주 오래전에 멈춘 상태
    ms.ensure_running()
    assert opened == [1]


def test_ensure_running_trusts_live_callbacks(monkeypatch):
    # 콜백이 최근에 들어왔다면(스트림 정상) 재생성하지 않는다.
    ms = MicStream()
    opened = []
    monkeypatch.setattr(ms, "_open", lambda: opened.append(1))
    ms._want_running = True
    ms._stream = _ZombieStream()
    ms._callback(_chunk(), 512, None, None)  # 방금 콜백 수신
    ms.ensure_running()
    assert opened == []
