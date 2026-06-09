import numpy as np

from jarvis.audio.playback import RingBuffer


def test_read_consumes_in_order():
    rb = RingBuffer()
    rb.write(np.array([1, 2, 3], dtype=np.float32))
    assert np.array_equal(rb.read(2), np.array([1, 2], dtype=np.float32))
    # read past the end pads with zeros (silence)
    assert np.array_equal(rb.read(3), np.array([3, 0, 0], dtype=np.float32))
    assert rb.pending() == 0


def test_clear_drops_pending():
    rb = RingBuffer()
    rb.write(np.ones(10, dtype=np.float32))
    assert rb.pending() == 10
    rb.clear()
    assert rb.pending() == 0
    out = rb.read(2)
    assert out.dtype == np.float32
    assert np.array_equal(out, np.zeros(2, dtype=np.float32))
