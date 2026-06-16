"""Config-driven TTS backend selection.

"auto" (default) picks the best available JARVIS voice chain:
  1. Trained RVC model present (voice_models/jarvis.pth + .venv-rvc) -> "melotts":
     native-Korean MeloTTS feeds the RVC timbre conversion (vc_backend="auto" pairs
     with this) — best Korean quality, no cross-lingual artifacts.
  2. Else XTTS runtime + reference wav -> "xtts": zero-shot JARVIS clone speaking
     Korean directly (good, but cross-lingual).
  3. Else macOS "say".
"xtts" / "melotts" / "say" force a specific backend.
"""
from __future__ import annotations

import os

from jarvis.tts.base import TTSBackend
from jarvis.vc.resolve import resolve_model_path


def _xtts_ready(settings) -> bool:
    return (os.path.exists(os.path.expanduser(settings.xtts_python))
            and os.path.exists(os.path.expanduser(settings.xtts_ref_path)))


def _pocket_ready(settings) -> bool:
    return (os.path.exists(os.path.expanduser(settings.pocket_python))
            and os.path.exists(os.path.expanduser(settings.pocket_ref_path)))


def _rvc_chain_ready(settings) -> bool:
    # Mirrors jarvis.vc.factory's auto gate (model + isolated runtime) and also needs
    # the MeloTTS worker venv that feeds the conversion.
    return (resolve_model_path(settings.rvc_model_path) is not None
            and os.path.exists(os.path.expanduser(settings.rvc_python))
            and os.path.exists(os.path.expanduser(settings.tts_worker_python)))


def make_tts(settings) -> TTSBackend:
    backend = settings.tts_backend
    if backend == "pocket" and not _pocket_ready(settings):
        backend = "auto"  # graceful fallback if .venv-pocket isn't set up here
    if backend == "auto":
        if _pocket_ready(settings):
            backend = "pocket"          # Kyutai Pocket TTS (English JARVIS voice)
        elif _rvc_chain_ready(settings):
            backend = "melotts"         # MeloTTS-KR -> trained RVC (Korean JARVIS)
        elif _xtts_ready(settings):
            backend = "xtts"
        else:
            backend = "say"
    if backend == "pocket":
        from jarvis.tts.pocket_tts import PocketTTS
        return PocketTTS(
            worker_cmd=[os.path.expanduser(settings.pocket_python),
                        "-m", "jarvis.tts.pocket_worker"],
            ref_path=settings.pocket_ref_path,
            hf_home=getattr(settings, "pocket_hf_home", "") or None)
    if backend == "say":
        from jarvis.tts.system_say import SystemSayTTS
        return SystemSayTTS()
    if backend == "edge":
        from jarvis.tts.edge_tts_backend import EdgeTTS
        return EdgeTTS(voice=getattr(settings, "edge_tts_voice", "en-GB-RyanNeural"))
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
