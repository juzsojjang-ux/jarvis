"""STT 백엔드 선택 — 맥 기본 mlx(애플 실리콘 빠름), 윈도우 faster-whisper."""
from __future__ import annotations
from jarvis.stt.base import STTBackend


def make_stt(settings) -> STTBackend:
    backend = getattr(settings, "stt_backend", "mlx")
    if backend == "faster":
        from jarvis.stt.faster_whisper_stt import FasterWhisperSTT
        return FasterWhisperSTT(settings.stt_repo, language=settings.language,
                                compute_type=getattr(settings, "faster_whisper_compute", "int8"))
    from jarvis.stt.mlx_whisper import MLXWhisperSTT
    return MLXWhisperSTT(settings.stt_repo, language=settings.language)
