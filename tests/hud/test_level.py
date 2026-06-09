import numpy as np

from jarvis.hud.level import audio_level


def test_empty_is_zero():
    assert audio_level(np.array([], dtype=np.float32)) == 0.0


def test_silence_is_zero():
    assert audio_level(np.zeros(1000, dtype=np.float32)) == 0.0


def test_clamped_to_one():
    assert audio_level(np.ones(1000, dtype=np.float32)) == 1.0


def test_louder_is_higher():
    quiet = audio_level(0.02 * np.ones(1000, dtype=np.float32))
    loud = audio_level(0.2 * np.ones(1000, dtype=np.float32))
    assert 0.0 < quiet < loud <= 1.0
