"""크로스플랫폼 음성 — Microsoft edge-tts(무료·키 불필요·맥/윈도우 공통).
edge-tts가 내놓는 mp3를 soundfile로 모노 float32로 디코드한다(ffmpeg 불필요).
오디오 인출은 주입 가능(_fetch)이라 테스트는 네트워크 없이 돈다.

합성이 실패하면 **무음을 조용히 반환하지 않는다** — 예전엔 그랬고, 그 탓에 배포 .app에서
edge-tts의 필수 의존성(aiosignal→aiohttp)이 번들에서 빠져 import가 죽어도 사용자에겐
'이유 없이 목소리만 안 남'으로 보였다(로그에도 흔적 없음). 이제는 실제 원인을 로깅하고,
macOS면 `say`로 폴백해 최소한 소리는 나게 한다. 폴백은 주입 가능(테스트·다른 플랫폼)."""
from __future__ import annotations

import io
import logging
import sys
from typing import Awaitable, Callable, Optional, Protocol

import numpy as np
import soundfile as sf

_log = logging.getLogger(__name__)


async def _edge_fetch(text: str, voice: str) -> bytes:
    import edge_tts
    chunks = bytearray()
    comm = edge_tts.Communicate(text, voice)
    async for part in comm.stream():
        if part.get("type") == "audio" and part.get("data"):
            chunks.extend(part["data"])
    return bytes(chunks)


class _FallbackTTS(Protocol):
    sample_rate: int
    async def synth(self, text: str) -> np.ndarray: ...


class EdgeTTS:
    """edge-tts 백엔드. voice는 영어 발화용(자비스는 영어로 말하고 한국어는 자막).
    기본 en-GB-RyanNeural(영국식 집사 톤). 한국어 직접 발화가 필요하면 ko 음성으로.

    fetch: 오디오 인출 주입(테스트용). fallback: edge 실패 시 쓸 TTS 주입(미지정 시
    macOS에서 자동으로 `say` 백엔드를 지연 생성; 비-macOS·생성 실패 시 무음)."""

    def __init__(self, voice: str = "en-GB-RyanNeural", sample_rate: int = 24000,
                 fetch: Optional[Callable[[str, str], Awaitable[bytes]]] = None,
                 fallback: Optional[_FallbackTTS] = None):
        self._voice = voice
        self.sample_rate = sample_rate
        self._fetch = fetch or _edge_fetch
        self._fallback = fallback
        self._fallback_tried = False

    def warm(self) -> None:
        return None

    async def synth(self, text: str) -> np.ndarray:
        text = (text or "").strip()
        if not text:
            return np.zeros(0, dtype=np.float32)
        try:
            audio = await self._fetch(text, self._voice)
            data, sr = sf.read(io.BytesIO(audio), dtype="float32")
            if data.ndim > 1:
                data = data.mean(axis=1)
            out = np.ascontiguousarray(data, dtype=np.float32)
            if out.size == 0:
                raise RuntimeError("edge-tts가 빈 오디오를 반환했습니다")
            self.sample_rate = int(sr)
            return out
        except Exception as exc:  # noqa: BLE001 - 실패는 로깅 + say 폴백(무음 금지)
            _log.warning("edge-tts 합성 실패(%s: %s) — say로 폴백",
                         type(exc).__name__, exc)
            print(f"[음성] edge-tts 실패: {type(exc).__name__}: {exc} — say로 폴백",
                  file=sys.stderr)
            return await self._say_fallback(text)

    async def _say_fallback(self, text: str) -> np.ndarray:
        """edge 실패 시 macOS `say`로 최소한의 음성을 낸다. 폴백 음성도 이후 RVC 음색
        변환을 거치므로 자비스 톤은 유지된다. 폴백조차 불가하면(비-macOS 등) 무음."""
        fb = self._fallback
        if fb is None:
            if sys.platform != "darwin":
                return np.zeros(0, dtype=np.float32)
            try:
                from jarvis.tts.system_say import SystemSayTTS
                fb = SystemSayTTS()
                self._fallback = fb
            except Exception as exc:  # noqa: BLE001
                _log.warning("say 폴백 생성 실패(%s: %s)", type(exc).__name__, exc)
                return np.zeros(0, dtype=np.float32)
        try:
            audio = await fb.synth(text)
            self.sample_rate = getattr(fb, "sample_rate", self.sample_rate)
            return np.ascontiguousarray(audio, dtype=np.float32)
        except Exception as exc:  # noqa: BLE001
            _log.warning("say 폴백 합성 실패(%s: %s)", type(exc).__name__, exc)
            return np.zeros(0, dtype=np.float32)
