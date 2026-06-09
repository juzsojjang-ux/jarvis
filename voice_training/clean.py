"""Denoise vocal clips with noisereduce (spectral gating, default path).

resemble-enhance is optional/fragile (Colab only); noisereduce is the default
on-device cleaner. prop_decrease=0.9 keeps speech intact while suppressing hiss.
"""
from __future__ import annotations

import numpy as np


def denoise(pcm, sr, prop_decrease: float = 0.9, stationary: bool = False) -> np.ndarray:
    import noisereduce as nr
    x = np.asarray(pcm, dtype=np.float32).reshape(-1)
    out = nr.reduce_noise(y=x, sr=sr, prop_decrease=prop_decrease, stationary=stationary)
    return np.asarray(out, dtype=np.float32)
