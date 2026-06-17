"""플랫폼별 음성 기본값 — 윈도우는 edge-tts→RVC + faster-whisper로 자동 전환.
맥/리눅스는 손대지 않는다. 사용자가 env(JARVIS_*)로 명시한 값은 건드리지 않기
위해, '현재 값이 그 필드의 기본값과 같을 때만' 덮어쓴다."""
from __future__ import annotations
import sys

# (필드, 윈도우 값, 맥 기본값) — 현재 값이 맥 기본과 같을 때만 윈도우 값으로 바꾼다.
# stt_repo: 맥 기본은 MLX 포맷 repo라 faster-whisper(CTranslate2)가 로드 못 한다. 윈도우는
# CT2 모델로 반드시 함께 바꿔야 한다(안 그러면 모델 로드 실패→모든 음성이 조용히 무시됨).
# "large-v3"는 faster-whisper가 Systran CT2 모델로 해석하는 size alias라 항상 받아진다.
_WIN_VOICE = [
    ("tts_backend", "edge", "pocket"),
    ("vc_backend", "rvc", "null"),
    ("rvc_f0_up", 0, -12),
    ("stt_backend", "faster", "mlx"),
    ("stt_repo", "large-v3", "mlx-community/whisper-large-v3-turbo"),
    ("ask_hotkey", "ctrl+space", "alt+space"),
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
