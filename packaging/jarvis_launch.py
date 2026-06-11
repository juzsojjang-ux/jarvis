"""PyInstaller entry-point shim for JARVIS (distributable).
배포 번들은 자비스 음색(edge-tts → ONNX RVC)을 기본으로 쓴다 — 사용자가 env로
명시하지 않았을 때만. dev(`python -m jarvis`)는 이 파일을 안 거쳐 현 설정(Pocket) 유지."""
import os

os.environ.setdefault("JARVIS_TTS_BACKEND", "edge")
os.environ.setdefault("JARVIS_VC_BACKEND", "onnx")
os.environ.setdefault("JARVIS_REPLY_LANGUAGE", "en")

from jarvis.__main__ import main

if __name__ == "__main__":
    main()
