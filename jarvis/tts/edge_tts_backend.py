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
from collections.abc import Awaitable, Callable
from typing import Protocol

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
                 fetch: Callable[[str, str], Awaitable[bytes]] | None = None,
                 fallback: _FallbackTTS | None = None):
        self._voice = voice
        self.sample_rate = sample_rate
        self._fetch = fetch or _edge_fetch
        self._fallback = fallback
        self._fallback_tried = False

    def warm(self) -> None:
        # alt(edge) 보이스도 부팅에서 스스로 초기화한다 — 기본 Pocket 경로의 예열을 동일하게 받게.
        # (1) edge_tts(aiohttp/aiosignal 등)를 미리 import: 번들 누락·환경 문제를 '첫 턴 무음'이
        #     아니라 부팅에서 로그/표준에러로 드러낸다. (2) OS 폴백(say/SAPI)을 선구축: 이후 어떤
        #     합성 실패에도 무음이 아니라 들리는 소리로 떨어진다(기본 음성을 먼저 돌릴 필요 없음).
        try:
            import edge_tts  # noqa: F401
        except Exception as exc:  # noqa: BLE001 - 예열 실패가 부팅을 막으면 안 된다
            _log.warning("edge-tts import 실패(예열) — OS 폴백 음성으로 말합니다 (%s: %s)",
                         type(exc).__name__, exc)
            print(f"[음성] edge-tts 사용 불가: {type(exc).__name__}: {exc} — OS 음성으로 폴백",
                  file=sys.stderr)
        if self._fallback is None:
            self._fallback = self._default_os_fallback()

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
        """edge 실패 시 OS 내장 음성으로 최소한의 소리를 낸다 — macOS는 `say`,
        윈도우는 SAPI(System.Speech). 폴백 음성도 이후 RVC 음색 변환을 거치므로 자비스
        톤은 유지된다. 폴백조차 불가하면(미지원 OS·도구 없음) 무음."""
        fb = self._fallback
        if fb is None:
            fb = self._default_os_fallback()
            if fb is None:
                return np.zeros(0, dtype=np.float32)
            self._fallback = fb
        try:
            audio = await fb.synth(text)
            self.sample_rate = getattr(fb, "sample_rate", self.sample_rate)
            return np.ascontiguousarray(audio, dtype=np.float32)
        except Exception as exc:  # noqa: BLE001
            _log.warning("OS 폴백 합성 실패(%s: %s)", type(exc).__name__, exc)
            return np.zeros(0, dtype=np.float32)

    @staticmethod
    def _default_os_fallback() -> _FallbackTTS | None:
        """플랫폼별 OS 내장 TTS 폴백을 만든다(macOS=say, 윈도우=SAPI). 없으면 None."""
        try:
            if sys.platform == "darwin":
                from jarvis.tts.system_say import SystemSayTTS
                return SystemSayTTS()
            if sys.platform.startswith("win"):
                from jarvis.tts.system_sapi import SystemSapiTTS
                return SystemSapiTTS()
        except Exception as exc:  # noqa: BLE001
            _log.warning("OS 폴백 생성 실패(%s: %s)", type(exc).__name__, exc)
        return None
