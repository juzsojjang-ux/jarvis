"""XTTS-v2 backend (TTSBackend): the real JARVIS voice via zero-shot cloning from the
reference clips — NO training, NO RVC model needed. Spawns the .venv-xtts worker
(jarvis.tts.xtts_worker) as a persistent subprocess and exchanges float32 PCM over
jarvis.tts.ipc. 24000 Hz.

Reuses MeloTTSKR's proc/warm/synth/close plumbing (identical IPC contract); only the
launch command and the extra worker env (reference path, device, language) differ.
"""
from __future__ import annotations

import asyncio
import os

from jarvis.tts.melotts_kr import MeloTTSKR


class XTTSBackend(MeloTTSKR):
    sample_rate: int = 24000

    def __init__(self, worker_cmd: list[str] | None = None, *, ref_path: str | None = None,
                 device: str = "cpu", language: str = "ko", repo_root: str | None = None):
        # NOTE: intentionally NOT calling super().__init__ (that wires the MeloTTS cmd);
        # we set the same fields the inherited methods use, with the XTTS worker + env.
        self.sample_rate = 24000
        self._cmd = worker_cmd or [
            os.path.expanduser("~/jarvis/.venv-xtts/bin/python"),
            "-m", "jarvis.tts.xtts_worker",
        ]
        self._repo_root = os.path.expanduser(repo_root or "~/jarvis")
        env = {
            **os.environ,
            "PYTHONPATH": self._repo_root,          # two-venv isolation: import jarvis.tts.*
            "COQUI_TOS_AGREED": "1",
            "JARVIS_XTTS_DEVICE": device,
            "JARVIS_XTTS_LANG": language,
        }
        if ref_path:
            env["JARVIS_XTTS_REF"] = os.path.expanduser(ref_path)
        self._env = env
        self._proc = None
        self._lock = asyncio.Lock()
