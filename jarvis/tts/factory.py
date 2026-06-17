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
import sys

from jarvis.tts.base import TTSBackend
from jarvis.vc.resolve import resolve_model_path


def _xtts_ready(settings) -> bool:
    return (os.path.exists(os.path.expanduser(settings.xtts_python))
            and os.path.exists(os.path.expanduser(settings.xtts_ref_path)))


def _pocket_ready(settings) -> bool:
    # frozen 번들: 워커는 본체 인터프리터(--child=jarvis.tts.pocket_worker)로 떠 별도
    # pocket_python venv가 필요 없다. 단 ref만 보면(경량 빌드에 ref 잔여 시) 거짓 ready로
    # 워커를 헛 spawn한다(audit r2) — 가중치 캐시(pocket_hf)까지 있어야 ready로 본다.
    # (FallbackTTS가 edge로 폴백하긴 하나, 애초에 헛 spawn을 막는다.)
    if getattr(sys, "frozen", False):
        hf = os.path.expanduser(getattr(settings, "pocket_hf_home", "") or "")
        return (bool(hf) and os.path.isdir(hf)
                and os.path.exists(os.path.expanduser(settings.pocket_ref_path)))
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
        if getattr(sys, "frozen", False):
            # 번들: 별도 venv 없이 본체 인터프리터를 --child= 로 재실행해 워커를 띄운다
            # (jarvis_launch._ALLOWED_CHILDREN 가 디스패치). _child_cmd와 동일한 형태.
            worker_cmd = [sys.executable, "--child=jarvis.tts.pocket_worker"]
        else:
            worker_cmd = [os.path.expanduser(settings.pocket_python),
                          "-m", "jarvis.tts.pocket_worker"]
        pocket = PocketTTS(
            worker_cmd=worker_cmd,
            ref_path=settings.pocket_ref_path,
            hf_home=getattr(settings, "pocket_hf_home", "") or None)
        # Pocket 워커가 죽어도(가중치 로드 실패·torch 문제 등) edge로 소리는 나게 감싼다.
        # (audit critical #2: 주석만 폴백을 약속했고 실제 폴백이 없어 런타임 실패 시 무음이던
        # 것을 실배선. edge는 자체적으로 say로 또 폴백 → Pocket→edge→say 3중 안전망.)
        from jarvis.tts.composite import FallbackTTS
        from jarvis.tts.edge_tts_backend import EdgeTTS
        edge = EdgeTTS(voice=getattr(settings, "edge_tts_voice", "en-GB-RyanNeural"))
        return FallbackTTS(pocket, edge)
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
