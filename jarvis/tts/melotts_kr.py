"""MeloTTS-KR backend (TTSBackend). Spawns the .venv-tts worker
(jarvis.tts.tts_worker) as a persistent subprocess and exchanges float32 PCM
over jarvis.tts.ipc. 44100 Hz mono.

TWO-VENV ISOLATION: .venv-tts does NOT pip-install the main package. The worker
reaches jarvis.tts.ipc + jarvis.tts.tts_worker (import-light: stdlib + numpy;
MeloTTS imported lazily inside the worker) ONLY because we launch the subprocess
with PYTHONPATH=<repo root> (default /Users/2seongjae/jarvis)."""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys

import numpy as np

from jarvis.tts import ipc


class MeloTTSKR:
    sample_rate: int = 44100

    def __init__(self, worker_cmd: list[str] | None = None, sample_rate: int = 44100,
                 repo_root: str | None = None):
        self.sample_rate = sample_rate
        self._cmd = worker_cmd or [
            os.path.expanduser("~/jarvis/.venv-tts/bin/python"),
            "-m", "jarvis.tts.tts_worker",
        ]
        # TWO-VENV ISOLATION: .venv-tts has no editable install of the main package,
        # so the worker can only import jarvis.tts.* via PYTHONPATH=<repo root>.
        self._repo_root = os.path.expanduser(repo_root or "~/jarvis")
        self._env = {**os.environ, "PYTHONPATH": self._repo_root}
        self._proc: subprocess.Popen | None = None
        self._lock = asyncio.Lock()

    def _ensure_proc(self) -> subprocess.Popen:
        if self._proc is None or self._proc.poll() is not None:
            self._proc = subprocess.Popen(
                self._cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=sys.stderr, bufsize=0, env=self._env)
        return self._proc

    def warm(self) -> None:
        proc = self._ensure_proc()
        proc.stdin.write(ipc.pack_request("준비 완료"))
        proc.stdin.flush()
        _pcm, sr = ipc.read_response(proc.stdout)  # discard warm-up audio
        self.sample_rate = sr

    _SYNTH_TIMEOUT = 45.0  # 워커 응답 상한(초) — 멈추면 죽이고 폴백

    async def synth(self, text: str) -> np.ndarray:
        async with self._lock:
            try:
                # 워커가 IPC read에서 멈추면(to_thread가 영원히 안 끝남) async with가 asyncio.Lock을
                # 영구히 잡아 이후 모든 synth가 데드락한다(audit r3 high). 타임아웃 + 워커 kill로
                # blocked readline을 EOF로 풀고 예외를 올려 FallbackTTS가 edge로 폴백하게 한다.
                pcm, _sr = await asyncio.wait_for(
                    asyncio.to_thread(self._synth_blocking, text),
                    timeout=self._SYNTH_TIMEOUT)
            except asyncio.TimeoutError as exc:
                self._kill_proc()
                raise RuntimeError("TTS 워커 응답 시간 초과") from exc
            return pcm

    def _synth_blocking(self, text: str):
        proc = self._ensure_proc()
        proc.stdin.write(ipc.pack_request(text))
        proc.stdin.flush()
        return ipc.read_response(proc.stdout)

    def _kill_proc(self) -> None:
        if self._proc is not None:
            try:
                self._proc.kill()
            except Exception:  # noqa: BLE001
                pass
            self._proc = None

    def close(self) -> None:
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.stdin.close()
                self._proc.wait(timeout=5)
            except Exception:
                self._proc.kill()
        self._proc = None
