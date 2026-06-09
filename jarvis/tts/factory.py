"""Config-driven TTS backend selection."""
from __future__ import annotations

import os

from jarvis.tts.base import TTSBackend


def make_tts(settings) -> TTSBackend:
    backend = settings.tts_backend
    if backend == "say":
        from jarvis.tts.system_say import SystemSayTTS
        return SystemSayTTS()
    if backend == "melotts":
        from jarvis.tts.melotts_kr import MeloTTSKR
        worker_python = os.path.expanduser(settings.tts_worker_python)
        return MeloTTSKR(worker_cmd=[worker_python, "-m", "jarvis.tts.tts_worker"])
    raise ValueError(f"unknown tts_backend: {backend!r}")
