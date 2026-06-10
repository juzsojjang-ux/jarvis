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
