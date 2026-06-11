"""Config-driven voice-conversion backend selection with JARVIS drop-in auto-detect.

vc_backend:
  "auto"  -> JARVIS RVC timbre IF the model is present AND the .venv-rvc runtime
             exists; otherwise the MeloTTS Korean voice (NullVC passthrough).
  "rvc"   -> force RVC; warn + fall back to NullVC if model/runtime is missing.
  "null"  -> force MeloTTS-only (NullVC).

The user's only action to enable the JARVIS voice is to drop jarvis.pth (+ optional
added_*.index) into voice_models/ — resolution + runtime gating happen here.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from jarvis.vc.base import VoiceConversion
from jarvis.vc.resolve import expand, resolve_index_path, resolve_model_path

_log = logging.getLogger(__name__)

# Standalone adapter shim, run INSIDE .venv-rvc (never imported by the main venv).
SHIM_PATH = Path(__file__).resolve().parent / "rvc_infer_cli.py"
# Persistent worker (loads models once; used by the live assistant).
WORKER_PATH = Path(__file__).resolve().parent / "rvc_worker.py"


def build_rvc_cmd(settings) -> list[str]:
    """The base command the RVC runtime is invoked with: the isolated interpreter
    plus the adapter shim. RVCConversion appends `convert <in> <out> --model ...`."""
    return [expand(settings.rvc_python), str(SHIM_PATH)]


def _runtime_ready(settings) -> bool:
    return os.path.exists(expand(settings.rvc_python))


def make_vc(settings) -> VoiceConversion:
    backend = settings.vc_backend
    if backend == "null":
        from jarvis.vc.null_vc import NullVC
        return NullVC()
    if backend == "onnx":
        m = os.path.expanduser(settings.onnx_model_path)
        cv = os.path.expanduser(settings.onnx_contentvec_path)
        if os.path.exists(m) and os.path.exists(cv):
            from jarvis.vc.onnx_rvc import OnnxRVCConversion
            return OnnxRVCConversion(m, cv, sample_rate=settings.rvc_sample_rate,
                                     f0_up=getattr(settings, "rvc_f0_up", 0))
        from jarvis.vc.null_vc import NullVC
        _log.warning("vc_backend=onnx but onnx models missing (%s / %s); NullVC.", m, cv)
        return NullVC()
    if backend not in ("auto", "rvc"):
        raise ValueError(f"unknown vc_backend: {backend!r}")

    from jarvis.vc.null_vc import NullVC
    model = resolve_model_path(settings.rvc_model_path)
    if model is None:
        # No JARVIS model yet — speak in the MeloTTS voice. (Explicit "rvc" warns.)
        msg = ("vc_backend=%r but no JARVIS model in %s; using MeloTTS voice. "
               "Drop jarvis.pth there to enable the JARVIS timbre.")
        (_log.warning if backend == "rvc" else _log.info)(
            msg, backend, os.path.dirname(expand(settings.rvc_model_path)))
        return NullVC()
    if not _runtime_ready(settings):
        _log.warning(
            "JARVIS model found (%s) but the RVC runtime is not installed at %s; "
            "using MeloTTS voice. Run voice_training/setup_rvc.sh once.",
            model, expand(settings.rvc_python))
        return NullVC()

    from jarvis.vc.rvc_persistent import PersistentRVC
    index = resolve_index_path(settings.rvc_model_path, settings.rvc_index_path)
    _log.info("JARVIS timbre active (RVC): model=%s index=%s", model, index or "<none>")
    # Persistent worker: hubert/rmvpe/model load once, not per sentence (latency).
    return PersistentRVC(
        model_path=model,
        index_path=index,
        sample_rate=settings.rvc_sample_rate,
        index_rate=settings.rvc_index_rate,
        f0_up=settings.rvc_f0_up,
        worker_cmd=[expand(settings.rvc_python), str(WORKER_PATH)])


def vc_status(settings) -> tuple[bool, str]:
    """(active, human_message) describing the current voice — for the startup banner
    and the voice_status tool. active=True only when the JARVIS timbre is live."""
    drop_dir = os.path.dirname(expand(settings.rvc_model_path))
    if settings.vc_backend == "null":
        if getattr(settings, "tts_backend", "") == "pocket":
            return (False, "음색 변환 꺼짐 — 포켓 TTS 자비스 음색(영어)으로 말합니다.")
        return (False, "음색 변환 꺼짐 — 멜로TTS 한국어 음성으로 말합니다.")
    model = resolve_model_path(settings.rvc_model_path)
    if model is None:
        return (False, f"자비스 음색 대기 중 — {drop_dir}/ 에 jarvis.pth를 넣으면 "
                       "자동으로 자비스 목소리가 켜집니다. 지금은 멜로TTS 음성입니다.")
    if not _runtime_ready(settings):
        return (False, "jarvis.pth 발견 — 추론 런타임(.venv-rvc)이 아직 없습니다. "
                       "voice_training/setup_rvc.sh 를 한 번 실행하면 완성됩니다. "
                       "지금은 멜로TTS 음성입니다.")
    return (True, "자비스 음색 활성화됨 — RVC로 실제 자비스 목소리로 말합니다.")
