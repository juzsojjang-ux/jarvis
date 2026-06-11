"""PyInstaller entry-point shim for JARVIS (distributable).
배포 번들은 자비스 음색(edge-tts → ONNX RVC)을 기본으로 쓴다 — 사용자가 env로
명시하지 않았을 때만. dev(`python -m jarvis`)는 이 파일을 안 거쳐 현 설정(Pocket) 유지."""
import os
import sys
from pathlib import Path

os.environ.setdefault("JARVIS_TTS_BACKEND", "edge")
os.environ.setdefault("JARVIS_VC_BACKEND", "onnx")
os.environ.setdefault("JARVIS_REPLY_LANGUAGE", "en")

# 프로즌 번들에서는 모델 파일이 ~/jarvis가 아니라 _MEIPASS/voice_models에 있다.
# config의 절대경로 기본값을 번들 경로로 덮어쓴다(사용자 env가 있으면 유지).
_meipass = getattr(sys, "_MEIPASS", None)
if _meipass:
    _vm = Path(_meipass) / "voice_models"
    os.environ.setdefault("JARVIS_ONNX_MODEL_PATH", str(_vm / "jarvis.onnx"))
    os.environ.setdefault("JARVIS_ONNX_CONTENTVEC_PATH", str(_vm / "vec-768-layer-12.onnx"))
    os.environ.setdefault("JARVIS_VAD_MODEL_PATH", str(_vm / "silero_vad.onnx"))

from jarvis.__main__ import main

if __name__ == "__main__":
    main()
