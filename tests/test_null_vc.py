import numpy as np

from jarvis.vc.null_vc import NullVC


def test_identity_passthrough_and_sample_rate():
    vc = NullVC()
    vc.warm()
    x = np.array([0.1, -0.2, 0.3], dtype=np.float32)
    out = vc.convert(x, in_rate=22050)
    assert np.array_equal(out, x)
    assert out.dtype == np.float32
    assert vc.sample_rate == 22050  # identity: output rate == input rate
