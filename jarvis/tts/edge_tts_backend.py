"""크로스플랫폼 음성 — Microsoft edge-tts(무료·키 불필요·맥/윈도우 공통).
edge-tts가 내놓는 mp3를 soundfile로 모노 float32로 디코드한다(ffmpeg 불필요).
오디오 인출은 주입 가능(_fetch)이라 테스트는 네트워크 없이 돈다."""
from __future__ import annotations

import io
from typing import Awaitable, Callable, Optional

import numpy as np
import soundfile as sf


async def _edge_fetch(text: str, voice: str) -> bytes:
    import edge_tts
    chunks = bytearray()
    comm = edge_tts.Communicate(text, voice)
    async for part in comm.stream():
        if part.get("type") == "audio" and part.get("data"):
            chunks.extend(part["data"])
    return bytes(chunks)


class EdgeTTS:
    """edge-tts 백엔드. voice는 영어 발화용(자비스는 영어로 말하고 한국어는 자막).
    기본 en-GB-RyanNeural(영국식 집사 톤). 한국어 직접 발화가 필요하면 ko 음성으로."""

    def __init__(self, voice: str = "en-GB-RyanNeural", sample_rate: int = 24000,
                 fetch: Optional[Callable[[str, str], Awaitable[bytes]]] = None):
        self._voice = voice
        self.sample_rate = sample_rate
        self._fetch = fetch or _edge_fetch

    def warm(self) -> None:
        return None

    async def synth(self, text: str) -> np.ndarray:
        text = (text or "").strip()
        if not text:
            return np.zeros(0, dtype=np.float32)
        try:
            audio = await self._fetch(text, self._voice)
            data, sr = sf.read(io.BytesIO(audio), dtype="float32")
            self.sample_rate = int(sr)
            if data.ndim > 1:
                data = data.mean(axis=1)
            return np.ascontiguousarray(data, dtype=np.float32)
        except Exception:  # noqa: BLE001 - 합성 실패는 무음 반환(호출부가 폴백)
            return np.zeros(0, dtype=np.float32)
