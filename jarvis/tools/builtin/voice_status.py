from __future__ import annotations

from typing import Any

from anthropic import beta_async_tool

from jarvis.vc.factory import vc_status


def make_voice_status_tool(settings: Any) -> Any:
    """Build a `voice_status` @beta_async_tool bound to live settings.

    Lets the user ask "내 목소리 지금 자비스로 나와?" and get the real state: JARVIS
    timbre active, or waiting for jarvis.pth, or waiting for the .venv-rvc runtime.
    """

    @beta_async_tool
    async def voice_status() -> str:
        """지금 자비스가 어떤 목소리(자비스 음색 RVC / 멜로TTS 한국어)로 말하는지,
        실제 자비스 목소리를 켜려면 무엇이 필요한지 알려줍니다."""
        _active, message = vc_status(settings)
        return message

    return voice_status
