"""윈도우 오프라인 폴백 음성 — Windows 내장 SAPI(System.Speech.Synthesis).

배포 .app의 기본 TTS는 edge-tts(온라인)다. edge가 실패하면 macOS는 `say`로 폴백하는데
(system_say.py), 윈도우엔 `say`가 없다. 그래서 윈도우에선 항상 깔려 있는 .NET
System.Speech 합성기를 PowerShell로 호출해 WAV로 렌더하고 모노 float32로 읽는다 —
오프라인·무설치·키 불필요. 폴백 음성도 이후 ONNX RVC 음색 변환을 거치므로 자비스 톤은
유지된다.

텍스트는 따옴표/특수문자 이스케이프 사고를 피하려 **환경변수로 전달**한다(명령줄 인젝션
회피). PowerShell·System.Speech가 없는 환경(비-윈도우)에서는 호출 자체가 실패하고,
상위(EdgeTTS._say_fallback)가 예외를 잡아 무음으로 떨어진다."""
from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
import wave

import numpy as np

# 텍스트를 SAPI로 받아 WAV로 떨구는 PowerShell 한 줄. 입력/출력은 환경변수로.
_PS_SCRIPT = (
    "Add-Type -AssemblyName System.Speech; "
    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
    "$s.Rate = [int]$env:JARVIS_SAPI_RATE; "
    "if ($env:JARVIS_SAPI_VOICE) { try { $s.SelectVoice($env:JARVIS_SAPI_VOICE) } catch {} }; "
    "$s.SetOutputToWaveFile($env:JARVIS_SAPI_OUT); "
    "$s.Speak($env:JARVIS_SAPI_TEXT); "
    "$s.Dispose()"
)


class SystemSapiTTS:
    """Windows SAPI 폴백. voice 미지정 시 시스템 기본 음성. rate는 -10~10(0=보통)."""

    def __init__(self, voice: str = "", rate: int = 0, sample_rate: int = 22050):
        self._voice = voice
        self._rate = rate
        self.sample_rate = sample_rate

    def warm(self) -> None:
        # SAPI는 항상 가용 — 미리 로드할 것 없음.
        return None

    async def synth(self, text: str) -> np.ndarray:
        return await asyncio.to_thread(self._synth, text)

    def _synth(self, text: str) -> np.ndarray:
        text = (text or "").strip()
        if not text:
            return np.zeros(0, dtype=np.float32)
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "sapi.wav")
            env = dict(
                os.environ,
                JARVIS_SAPI_TEXT=text,
                JARVIS_SAPI_OUT=out,
                JARVIS_SAPI_RATE=str(int(self._rate)),
                JARVIS_SAPI_VOICE=self._voice or "",
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-Command", _PS_SCRIPT],
                check=True, env=env, timeout=30,   # PowerShell SAPI가 멈춰 폴백이 영구 정지하는 것 방지(audit r3)
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            with wave.open(out, "rb") as f:
                self.sample_rate = f.getframerate()
                channels = f.getnchannels()
                sampwidth = f.getsampwidth()
                raw = f.readframes(f.getnframes())
        return _pcm_to_mono_float32(raw, channels, sampwidth)


def _pcm_to_mono_float32(raw: bytes, channels: int, sampwidth: int) -> np.ndarray:
    """SAPI WAV(보통 16-bit PCM, 드물게 8-bit)를 모노 float32 [-1,1]로."""
    if sampwidth == 2:
        pcm = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif sampwidth == 1:
        # 8-bit WAV은 unsigned(0~255), 128이 0점.
        pcm = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        # 예상 밖 포맷이면 빈 배열(상위가 무음 처리) — 잘못 디코드해 잡음 내는 것보단 낫다.
        return np.zeros(0, dtype=np.float32)
    if channels > 1:
        pcm = pcm.reshape(-1, channels).mean(axis=1)
    return np.ascontiguousarray(pcm, dtype=np.float32)
