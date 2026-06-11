"""플랫폼별 음성 기본값 — 윈도우는 edge-tts→RVC + faster-whisper로 자동 전환.
맥/리눅스는 손대지 않는다. 사용자가 env(JARVIS_*)로 명시한 값은 건드리지 않기
위해, '현재 값이 그 필드의 기본값과 같을 때만' 덮어쓴다."""
from __future__ import annotations
import sys

# (필드, 윈도우 값, 맥 기본값) — 현재 값이 맥 기본과 같을 때만 윈도우 값으로 바꾼다.
_WIN_VOICE = [
    ("tts_backend", "edge", "pocket"),
    ("vc_backend", "rvc", "null"),
    ("rvc_f0_up", 0, -12),
    ("stt_backend", "faster", "mlx"),
]


def apply_platform_defaults(settings, system: str | None = None) -> None:
    sysname = system if system is not None else sys.platform
    if not str(sysname).startswith("win"):
        return  # 맥/리눅스: 무변경
    for field, win_val, mac_default in _WIN_VOICE:
        if getattr(settings, field, mac_default) == mac_default:
            try:
                setattr(settings, field, win_val)
            except Exception:  # noqa: BLE001 - 설정이 frozen이면 무시
                pass
