import numpy as np

from voice_training import clean


def test_denoise_keeps_shape_and_reduces_energy():
    sr = 16000
    rng = np.random.default_rng(0)
    t = np.arange(2 * sr) / sr
    tone = 0.3 * np.sin(2 * np.pi * 200 * t).astype(np.float32)
    noisy = (tone + 0.05 * rng.standard_normal(t.size)).astype(np.float32)
    out = clean.denoise(noisy, sr, stationary=True)
    assert out.shape == noisy.shape and out.dtype == np.float32

    def rms(x):
        return float(np.sqrt(np.mean(x ** 2)))

    assert rms(out) <= rms(noisy) + 1e-6
