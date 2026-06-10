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


def test_chunk_levels_follow_audio_shape():
    from jarvis.hud.level import chunk_levels
    sr = 1000
    # 0.3s loud + 0.3s silence -> 6 hops at 0.1s: first 3 loud, last 3 zero
    pcm = np.concatenate([0.5 * np.ones(300, np.float32), np.zeros(300, np.float32)])
    levels = chunk_levels(pcm, sr, hop_s=0.1)
    assert len(levels) == 6
    assert all(lv > 0.5 for lv in levels[:3])
    assert all(lv == 0.0 for lv in levels[3:])


def test_capture_level_tail_peeks_without_drain():
    from jarvis.audio.capture import MicCapture
    cap = MicCapture()
    cap._frames = [0.1 * np.ones(800, np.float32), 0.2 * np.ones(800, np.float32)]
    tail = cap.level_tail(window=1600)
    assert tail.shape[0] == 1600
    assert len(cap._frames) == 2  # peek must not consume
    assert audio_level(tail) > 0.0
