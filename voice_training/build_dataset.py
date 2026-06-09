"""Local dataset build: raw vocals WAVs -> isolated -> 3-12s clips -> denoise
-> 40kHz mono s16. RVC TRAINING itself is CUDA/Colab only (see README +
train_colab.ipynb); this only prepares the dataset locally.

Usage:
    python -m voice_training.build_dataset --raw RAW --work WORK --out OUT
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from voice_training import clean, resample, segment, separate


def build_one(in_wav: str, work_dir: Path, out_dir: Path, separator) -> list[str]:
    import soundfile as sf
    work_dir, out_dir = Path(work_dir), Path(out_dir)
    vocals = separate.separate_vocals(separator, in_wav)
    pcm, sr = sf.read(vocals, dtype="float32")
    if pcm.ndim > 1:
        pcm = pcm.mean(axis=1).astype(np.float32)
    segs = segment.find_segments(pcm, sr)
    clip_paths = segment.export_segments(pcm, sr, segs, work_dir / Path(in_wav).stem)
    finals: list[str] = []
    for clip in clip_paths:
        cp, csr = sf.read(clip, dtype="float32")
        sf.write(clip, clean.denoise(cp, csr), csr)
        out_wav = out_dir / (Path(clip).stem + "_40k.wav")
        resample.resample_file(clip, out_wav)
        finals.append(str(out_wav))
    return finals


def main(argv=None) -> list[str]:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model-dir",
                    default=str(Path.home() / ".cache" / "audio-separator-models"))
    a = ap.parse_args(argv)
    work, out = Path(a.work), Path(a.out)
    work.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    if not separate.check_env():
        raise RuntimeError("CoreMLExecutionProvider missing; run: audio-separator --env_info")
    sep = separate.build_separator(work, a.model_dir)
    finals: list[str] = []
    for raw in sorted(Path(a.raw).glob("*.wav")):
        finals.extend(build_one(str(raw), work, out, sep))
    print(f"built {len(finals)} clips -> {out}")
    return finals


if __name__ == "__main__":
    main()
