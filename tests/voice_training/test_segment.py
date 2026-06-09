import numpy as np

from voice_training import segment


def _tone(dur_s, sr=16000, f=220.0):
    t = np.arange(int(dur_s * sr)) / sr
    return (0.5 * np.sin(2 * np.pi * f * t)).astype(np.float32)


def test_find_segments_splits_on_silence():
    sr = 16000
    sig = np.concatenate([_tone(4, sr), np.zeros(int(0.5 * sr), np.float32), _tone(5, sr)])
    segs = segment.find_segments(sig, sr, min_s=3.0, max_s=12.0)
    assert len(segs) == 2
    for s, e in segs:
        assert 3.0 <= (e - s) / sr <= 12.0


def test_find_segments_hard_splits_long_run():
    sr = 16000
    segs = segment.find_segments(_tone(20, sr), sr, min_s=3.0, max_s=12.0)
    assert all((e - s) / sr <= 12.0 for s, e in segs)
    assert sum(e - s for s, e in segs) > 12 * sr


def test_export_segments_writes_wavs(tmp_path):
    import soundfile as sf
    sr = 16000
    sig = _tone(4, sr)
    paths = segment.export_segments(sig, sr, [(0, len(sig))], tmp_path)
    data, rate = sf.read(paths[0], dtype="float32")
    assert len(paths) == 1 and rate == sr and len(data) == len(sig)
