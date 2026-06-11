"""프로바이더 키 검증 — 작은 테스트 호출. 클라이언트 주입 가능(테스트는 가짜)."""
from __future__ import annotations

from typing import Any, Optional


async def validate(
    provider: str,
    key: str,
    *,
    gemini_client: Any = None,
    openai_client: Any = None,
) -> tuple[bool, str]:
    provider = (provider or "").strip()

    if provider == "claude":
        return True, "Claude 구독으로 사용합니다."

    if provider == "gemini":
        if not key.strip():
            return False, "Gemini API 키를 입력하세요."
        try:
            client = gemini_client
            if client is None:
                from google import genai  # type: ignore[import]

                client = genai.Client(api_key=key)
            await client.aio.models.generate_content(
                model="gemini-2.5-flash", contents="hi"
            )
            return True, "Gemini 키가 확인되었습니다."
        except Exception:  # noqa: BLE001
            return False, "Gemini 키가 올바르지 않습니다."

    if provider == "gpt":
        if not key.strip():
            return False, "OpenAI API 키를 입력하세요."
        try:
            client = openai_client
            if client is None:
                from openai import AsyncOpenAI  # type: ignore[import]

                client = AsyncOpenAI(api_key=key)
            await client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=1,
            )
            return True, "OpenAI 키가 확인되었습니다."
        except Exception:  # noqa: BLE001
            return False, "OpenAI 키가 올바르지 않습니다."

    return False, "알 수 없는 프로바이더입니다."
