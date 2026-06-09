"""Config-driven TTS backend selection.

"auto" (default): the JARVIS voice (XTTS-v2 zero-shot clone) when the .venv-xtts runtime
AND a reference wav exist; otherwise the macOS `say` voice. "xtts" forces XTTS, "melotts"
forces MeloTTS-KR, "say" forces macOS say.
"""
from __future__ import annotations

import os

from jarvis.tts.base import TTSBackend


def _xtts_ready(settings) -> bool:
    return (os.path.exists(os.path.expanduser(settings.xtts_python))
            and os.path.exists(os.path.expanduser(settings.xtts_ref_path)))


def make_tts(settings) -> TTSBackend:
    backend = settings.tts_backend
    if backend == "auto":
        backend = "xtts" if _xtts_ready(settings) else "say"
    if backend == "say":
        from jarvis.tts.system_say import SystemSayTTS
        return SystemSayTTS()
    if backend == "melotts":
        from jarvis.tts.melotts_kr import MeloTTSKR
        worker_python = os.path.expanduser(settings.tts_worker_python)
        return MeloTTSKR(worker_cmd=[worker_python, "-m", "jarvis.tts.tts_worker"])
    if backend == "xtts":
        from jarvis.tts.xtts_kr import XTTSBackend
        worker_python = os.path.expanduser(settings.xtts_python)
        return XTTSBackend(
            worker_cmd=[worker_python, "-m", "jarvis.tts.xtts_worker"],
            ref_path=settings.xtts_ref_path,
            device=settings.xtts_device,
            language=settings.language)
    raise ValueError(f"unknown tts_backend: {backend!r}")
