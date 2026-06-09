from __future__ import annotations

import asyncio
from typing import Any

_YES: tuple[str, ...] = (
    "네", "예", "응", "그래", "좋아", "진행",
    "확인", "맞아", "yes", "ok", "오케이",
)
_NO: tuple[str, ...] = (
    "아니", "아니오", "아니요", "취소", "안돼",
    "안 돼", "그만", "하지마", "싫", "no",
)


def parse_korean_confirmation(text: str) -> bool | None:
    """Parse a short Korean utterance into yes(True)/no(False)/unclear(None).

    Negatives are checked FIRST: for an irreversible action, anything that
    sounds like refusal must block, so an ambiguous reply never confirms.
    """
    t = text.strip().lower()
    if not t:
        return None
    if any(k in t for k in _NO):
        return False
    if any(k in t for k in _YES):
        return True
    return None


class VoiceConfirm:
    """Real voice confirmation for gated tools.

    Speaks the prompt through the live TTS->VC->playback path, records a short
    reply window from the mic, transcribes it, and parses a Korean yes/no.
    Injected as ``Brain.confirm``. The parser is unit-tested; the live capture
    path is manual-verified.
    """

    def __init__(
        self,
        *,
        tts: Any,
        vc: Any,
        playback: Any,
        capture: Any,
        stt: Any,
        settings: Any,
        window_s: float = 4.0,
    ) -> None:
        self._tts = tts
        self._vc = vc
        self._playback = playback
        self._capture = capture
        self._stt = stt
        self._settings = settings
        self._window_s = window_s

    async def confirm(self, prompt: str) -> bool:
        await self._speak(
            f"{prompt} 진행하려면 '네', 취소하려면 '아니오'라고 말씀해 주세요."
        )
        self._capture.start()
        await asyncio.sleep(self._window_s)
        pcm = self._capture.stop()
        text = await asyncio.to_thread(
            self._stt.transcribe, pcm, 16000, self._settings.language
        )
        return parse_korean_confirmation(text) is True

    async def _speak(self, text: str) -> None:
        # Lazy import keeps module import light (parser tests need no soxr).
        from jarvis.audio.util import resample

        audio = await self._tts.synth(text)
        converted = await asyncio.to_thread(self._vc.convert, audio, self._tts.sample_rate)
        out = resample(converted, self._vc.sample_rate, self._settings.playback_rate)
        self._playback.feed(out)
        # Let the prompt finish before opening the reply window.
        await asyncio.sleep(len(out) / self._settings.playback_rate)
