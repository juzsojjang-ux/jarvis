"""RVC voice conversion (JARVIS timbre). Primary: mlx-rvc CLI on Apple Silicon.
Fallback (A/B only): PyTorch-MPS fork NevilPatel01/RVC-WebUI-MacOS -- same
.pth/.index, swap rvc_cmd. Validate timbre on 3 held-out clips vs the fork
before committing index_rate/f0_up; mlx-rvc should match within perceptual tol.

Model sample rate is per-.pth (40000 or 48000). convert() resamples the input
to 40000 Hz (RVC ingest) via jarvis.audio.util.resample, runs inference (RMVPE
f0), and returns float32 at self.sample_rate (the model's output rate). The
orchestrator then resamples self.sample_rate -> playback_rate (48000)."""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import numpy as np

from jarvis.audio.util import resample

RVC_INGEST_RATE = 40000


class RVCConversion:
    def __init__(self, model_path: str, index_path: str | None = None,
                 sample_rate: int = 40000,
                 f0_method: str = "rmvpe", index_rate: float = 0.75,
                 f0_up: int = 0, rvc_cmd: list[str] | None = None):
        self.model_path = str(model_path)
        # Index is OPTIONAL: RVC converts on the .pth alone (index improves similarity).
        self.index_path = str(index_path) if index_path else None
        self.sample_rate = sample_rate
        self.f0_method = f0_method
        self.index_rate = index_rate
        self.f0_up = f0_up
        self._rvc_cmd = rvc_cmd or ["mlx-rvc"]

    def _build_command(self, in_wav: str, out_wav: str) -> list[str]:
        cmd = [*self._rvc_cmd, "convert", in_wav, out_wav, "--model", self.model_path]
        if self.index_path:
            cmd += ["--index", self.index_path]
        cmd += ["--index-rate", str(self.index_rate),
                "--f0-method", self.f0_method, "--pitch", str(self.f0_up)]
        return cmd

    def warm(self) -> None:
        self.convert(np.zeros(int(0.5 * RVC_INGEST_RATE), dtype=np.float32), RVC_INGEST_RATE)

    def convert(self, pcm, in_rate: int, runner=subprocess.run) -> np.ndarray:
        import soundfile as sf
        x = np.asarray(pcm, dtype=np.float32).reshape(-1)
        if in_rate != RVC_INGEST_RATE:
            x = resample(x, in_rate, RVC_INGEST_RATE)
        with tempfile.TemporaryDirectory() as d:
            in_wav = str(Path(d) / "in.wav")
            out_wav = str(Path(d) / "out.wav")
            sf.write(in_wav, x, RVC_INGEST_RATE)
            runner(self._build_command(in_wav, out_wav), check=True)
            out, sr = sf.read(out_wav, dtype="float32")
        out = np.asarray(out, dtype=np.float32).reshape(-1)
        if sr != self.sample_rate:
            out = resample(out, sr, self.sample_rate)
        return out
