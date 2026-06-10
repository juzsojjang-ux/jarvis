"""Pocket-TTS backend (TTSBackend): the JARVIS voice via Kyutai Pocket TTS cloning —
the engine from the NetHyTech video. English-only, CPU real-time. Spawns the .venv-pocket
worker (jarvis.tts.pocket_worker) and exchanges float32 PCM over jarvis.tts.ipc. 24000 Hz.

Reuses MeloTTSKR's proc/warm/synth/close plumbing (identical IPC contract); only the
launch command and the worker env (reference path) differ.
"""
from __future__ import annotations

import asyncio
import os

from jarvis.tts.melotts_kr import MeloTTSKR


class PocketTTS(MeloTTSKR):
    sample_rate: int = 24000

    def __init__(self, worker_cmd: list[str] | None = None, *, ref_path: str | None = None,
                 repo_root: str | None = None):
        # NOTE: intentionally NOT calling super().__init__ (it wires the MeloTTS cmd).
        self.sample_rate = 24000
        self._cmd = worker_cmd or [
            os.path.expanduser("~/jarvis/.venv-pocket/bin/python"),
            "-m", "jarvis.tts.pocket_worker",
        ]
        self._repo_root = os.path.expanduser(repo_root or "~/jarvis")
        env = {**os.environ, "PYTHONPATH": self._repo_root}
        if ref_path:
            env["JARVIS_POCKET_REF"] = os.path.expanduser(ref_path)
        self._env = env
        self._proc = None
        self._lock = asyncio.Lock()
