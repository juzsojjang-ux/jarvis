"""Resample cleaned clips to RVC training format: 40000 Hz mono s16 WAV (ffmpeg)."""
from __future__ import annotations

import subprocess
from pathlib import Path


def build_ffmpeg_resample_cmd(in_wav, out_wav, rate: int = 40000) -> list[str]:
    return ["ffmpeg", "-y", "-i", str(in_wav),
            "-ar", str(rate), "-ac", "1", "-sample_fmt", "s16", str(out_wav)]


def resample_file(in_wav, out_wav, rate: int = 40000, runner=subprocess.run) -> str:
    Path(out_wav).parent.mkdir(parents=True, exist_ok=True)
    runner(build_ffmpeg_resample_cmd(in_wav, out_wav, rate), check=True)
    return str(out_wav)
