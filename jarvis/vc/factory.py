"""Config-driven voice-conversion backend selection."""
from __future__ import annotations

import logging
import os

from jarvis.vc.base import VoiceConversion

_log = logging.getLogger(__name__)


def make_vc(settings) -> VoiceConversion:
    backend = settings.vc_backend
    if backend == "null":
        from jarvis.vc.null_vc import NullVC
        return NullVC()
    if backend == "rvc":
        from jarvis.vc.null_vc import NullVC
        from jarvis.vc.rvc import RVCConversion
        model_path = os.path.expanduser(settings.rvc_model_path)
        index_path = os.path.expanduser(settings.rvc_index_path)
        if not os.path.exists(model_path):
            # spec 8.4 bootstrap: the JARVIS voice path must run BEFORE Colab training
            # produces jarvis.pth. Fall back to identity passthrough so the MeloTTS
            # voice still plays (no timbre conversion yet).
            _log.warning(
                "vc_backend='rvc' but model %s is absent; falling back to NullVC "
                "(run voice_training -> Colab to produce jarvis.pth + .index).",
                model_path)
            return NullVC()
        return RVCConversion(
            model_path=model_path,
            index_path=index_path,
            sample_rate=settings.rvc_sample_rate,
            index_rate=settings.rvc_index_rate,
            f0_up=settings.rvc_f0_up)
    raise ValueError(f"unknown vc_backend: {backend!r}")
