"""PersistentRVC: the JARVIS timbre conversion against a long-lived .venv-rvc worker.

Same VoiceConversion contract as RVCConversion (sample_rate / warm() / convert()),
but hubert+rmvpe+model load ONCE in the worker (jarvis.vc.rvc_worker) instead of on
every sentence — per-sentence latency drops from ~10s to roughly real conversion time.
Audio crosses the boundary as temp wav files; control flows over a line protocol.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import numpy as np

from jarvis.audio.util import resample

RVC_INGEST_RATE = 40000
WORKER_PATH = Path(__file__).resolve().parent / "rvc_worker.py"


class PersistentRVC:
    def __init__(self, model_path: str, index_path: str | None = None,
                 sample_rate: int = 40000, f0_method: str = "rmvpe",
                 index_rate: float = 0.9, f0_up: int = -12,
                 worker_cmd: list[str] | None = None, ready_timeout: float = 180.0):
        self.model_path = str(model_path)
        self.index_path = str(index_path) if index_path else None
        self.sample_rate = sample_rate
        self.f0_method = f0_method
        self.index_rate = index_rate
        self.f0_up = f0_up
        self._cmd = worker_cmd or [
            os.path.expanduser("~/jarvis/.venv-rvc/bin/python"), str(WORKER_PATH)]
        self._ready_timeout = ready_timeout
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def _env(self) -> dict[str, str]:
        env = {
            **os.environ,
            "JARVIS_RVC_MODEL": self.model_path,
            "JARVIS_RVC_INDEX": self.index_path or "",
            "JARVIS_RVC_INDEX_RATE": str(self.index_rate),
            "JARVIS_RVC_F0_UP": str(self.f0_up),
            "JARVIS_RVC_F0_METHOD": self.f0_method,
        }
        env.setdefault("JARVIS_RVC_DEVICE", "mps")
        return env

    def _ensure_proc(self) -> subprocess.Popen:
        if self._proc is None or self._proc.poll() is not None:
            self._proc = subprocess.Popen(
                self._cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=sys.stderr, text=True, bufsize=1, env=self._env())
            line = self._proc.stdout.readline().strip()  # blocks until models load
            if line != "READY":
                raise RuntimeError(f"RVC worker failed to start: {line!r}")
        return self._proc

    def warm(self) -> None:
        self._ensure_proc()
        self.convert(np.zeros(int(0.5 * RVC_INGEST_RATE), dtype=np.float32), RVC_INGEST_RATE)

    def convert(self, pcm, in_rate: int) -> np.ndarray:
        import soundfile as sf
        x = np.asarray(pcm, dtype=np.float32).reshape(-1)
        if in_rate != RVC_INGEST_RATE:
            x = resample(x, in_rate, RVC_INGEST_RATE)
        with self._lock:
            proc = self._ensure_proc()
            with tempfile.TemporaryDirectory() as d:
                in_wav = str(Path(d) / "in.wav")
                out_wav = str(Path(d) / "out.wav")
                sf.write(in_wav, x, RVC_INGEST_RATE)
                proc.stdin.write(f"CONVERT\t{in_wav}\t{out_wav}\n")
                proc.stdin.flush()
                reply = proc.stdout.readline().strip()
                if reply != "OK":
                    raise RuntimeError(f"RVC worker error: {reply!r}")
                out, sr = sf.read(out_wav, dtype="float32")
        out = np.asarray(out, dtype=np.float32).reshape(-1)
        self.sample_rate = int(sr)  # model's true output rate
        return out

    def close(self) -> None:
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.stdin.close()
                self._proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                self._proc.kill()
        self._proc = None
