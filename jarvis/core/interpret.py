"""통역 모드 보조: 언어 감지(한글 음절 존재)와 한국어 음성 출력(macOS say).
현 TTS는 Pocket 영어 전용이라 통역의 한국어 방향은 say로 직접 재생한다."""
from __future__ import annotations

import os
import subprocess
import sys

_WIN_SAY_PS = (
    "Add-Type -AssemblyName System.Speech;"
    "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
    "$s.Speak($env:JARVIS_SAY_TEXT);$s.Dispose()"
)


def detect_lang(text: str) -> str:
    """한글 음절(가–힣)이 하나라도 있으면 'ko', 아니면 'en'. 주인님은 한국어
    화자라 혼합 발화는 한국어로 본다(영어로 통역해 주는 게 자연스럽다)."""
    if any("가" <= ch <= "힣" for ch in (text or "")):
        return "ko"
    return "en"


def interpret_speak_korean(text: str, voice: str = "Yuna",
                           runner=subprocess.run) -> None:
    """macOS say로 한국어를 기본 출력장치에 재생. 실패는 조용히 무시(통역
    한 줄이 모드를 깨면 안 된다)."""
    text = (text or "").strip()
    if not text:
        return
    try:
        if sys.platform == "darwin":
            runner(["say", "-v", voice, text], capture_output=True, text=True, timeout=30)
        elif sys.platform.startswith("win"):
            # 윈도우는 say가 없어 통역 한국어가 무음이던 것(audit r4) — System.Speech로 재생.
            env = dict(os.environ, JARVIS_SAY_TEXT=text)
            runner(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-Command", _WIN_SAY_PS],
                   capture_output=True, text=True, timeout=30, env=env)
        # 그 외(리눅스): 직접 재생 수단이 없어 조용히 스킵
    except Exception:  # noqa: BLE001 - 음성 출력 실패가 통역 모드를 멈추면 안 된다
        pass
