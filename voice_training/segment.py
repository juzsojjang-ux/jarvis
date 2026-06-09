"""Split a long vocal track into 3-12s utterance clips by silence.

Energy-gated, pure-numpy so it is unit-testable without ffmpeg. 20ms frames
below silence_thresh_db are silence; a silent run >= min_silence_s cuts the
voiced span. Voiced spans shorter than min_s are dropped; spans longer than
max_s are hard-split at max_s.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np


def _frame_rms_db(pcm: np.ndarray, frame: int) -> np.ndarray:
    n = len(pcm) // frame
    if n == 0:
        return np.array([], dtype=np.float64)
    blk = pcm[: n * frame].reshape(n, frame).astype(np.float64)
    rms = np.sqrt(np.mean(blk ** 2, axis=1) + 1e-12)
    return 20.0 * np.log10(rms + 1e-12)


def find_segments(pcm, sr, min_s=3.0, max_s=12.0,
                  silence_thresh_db=-40.0, min_silence_s=0.3):
    pcm = np.asarray(pcm, dtype=np.float32).reshape(-1)
    frame = max(1, int(sr * 0.02))
    voiced = _frame_rms_db(pcm, frame) > silence_thresh_db
    min_sil = max(1, int(round(min_silence_s / 0.02)))
    min_len, max_len = int(min_s * sr), int(max_s * sr)
    segs, i, nf = [], 0, len(voiced)
    while i < nf:
        if not voiced[i]:
            i += 1
            continue
        j, sil = i, 0
        while j < nf:
            if voiced[j]:
                sil, j = 0, j + 1
            else:
                sil += 1
                if sil >= min_sil:
                    break
                j += 1
        end_frame = j - sil if sil else j
        start, end = i * frame, min(len(pcm), end_frame * frame)
        span = start
        while end - span > max_len:
            segs.append((span, span + max_len))
            span += max_len
        if end - span >= min_len:
            segs.append((span, end))
        i = j + 1
    return segs


def export_segments(pcm, sr, segs, out_dir, prefix="seg") -> list[str]:
    import soundfile as sf
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for k, (s, e) in enumerate(segs):
        p = out / f"{prefix}_{k:04d}.wav"
        sf.write(str(p), np.asarray(pcm[s:e], dtype=np.float32), sr)
        paths.append(str(p))
    return paths
