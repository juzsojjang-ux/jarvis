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
        # 영어 전용 음성(Pocket/edge)에 한국어를 넣으면 웅얼거림으로 뭉개진다 —
        # 영어 음성 모드에선 영어로 묻고, 한국어 상세는 우측 패널에 띄운다(영화식).
        english_voice = str(getattr(self._settings, "reply_language", "ko")
                            ).lower().startswith("en")
        try:
            from jarvis.hud import notice_bus
            notice_bus.show(f"확인 필요\n{prompt}\n('네' / '아니오')")
        except Exception:  # noqa: BLE001 - 패널은 보조, 확인 흐름을 막지 않는다
            pass
        if english_voice:
            await self._speak("Confirmation needed, sir — yes or no?")
        else:
            # 짧게 — 긴 안내문은 Pocket TTS 토큰 한도(50)를 넘겨 단어가 잘렸다.
            await self._speak(f"{prompt} 네 또는 아니오로 답해 주세요.")
        # try/finally: 확인 턴이 취소(바지인)·예외로 중단돼도 마이크 캡처를 반드시 닫는다
        # (audit r4: start 후 stop이 안 불려 PTT 전용 모드서 마이크가 켜진 채 남던 것).
        self._capture.start()
        try:
            await asyncio.sleep(self._window_s)
        finally:
            pcm = self._capture.stop()
        text = await asyncio.to_thread(
            self._stt.transcribe, pcm, 16000, self._settings.language
        )
        try:
            from jarvis.hud import notice_bus
            notice_bus.hide()  # 확인 패널 정리(응답을 받았으니)
        except Exception:  # noqa: BLE001
            pass
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
