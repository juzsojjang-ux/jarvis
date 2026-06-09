import numpy as np
import soundfile as sf

from voice_training import build_dataset


def test_build_one_runs_pipeline_in_order(tmp_path, monkeypatch):
    order = []
    bd = build_dataset
    monkeypatch.setattr(bd.separate, "separate_vocals",
                        lambda sep, w: order.append("separate") or str(tmp_path / "voc.wav"))
    monkeypatch.setattr(bd.segment, "find_segments",
                        lambda pcm, sr, **k: order.append("segment") or [(0, len(pcm))])
    monkeypatch.setattr(bd.segment, "export_segments",
                        lambda pcm, sr, segs, d, **k: [str(tmp_path / "c0.wav")])
    monkeypatch.setattr(bd.clean, "denoise",
                        lambda pcm, sr, **k: order.append("clean") or pcm)
    monkeypatch.setattr(bd.resample, "resample_file",
                        lambda i, o, **k: order.append("resample") or str(o))
    sr = 16000
    sf.write(tmp_path / "voc.wav", np.zeros(sr, np.float32), sr)
    sf.write(tmp_path / "c0.wav", np.zeros(sr, np.float32), sr)
    out = build_dataset.build_one(str(tmp_path / "raw.wav"), tmp_path, tmp_path, separator=object())
    assert order == ["separate", "segment", "clean", "resample"]
    assert out and out[0].endswith("_40k.wav")
