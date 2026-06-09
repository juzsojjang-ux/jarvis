from __future__ import annotations

from collections.abc import AsyncIterator

from anthropic import AsyncAnthropic

_GUIDANCE = (
    "너는 자비스, 음성으로 답하는 한국어 집사다. 최종적으로 말할 한국어 답변만 출력하라. "
    "사고 과정, 머리말, 맺음말, '음' 같은 군더더기 없이 핵심부터 간결하게 답하라."
)


class Brain:
    """Conversational path (M1): Haiku streaming with cached persona prefix +
    memory injection. Gated tool loop is added in M3."""

    def __init__(
        self,
        settings,
        memory,
        persona_text: str,
        client: AsyncAnthropic | None = None,
    ):
        self._settings = settings
        self._memory = memory
        self._persona = persona_text
        self._client = client or AsyncAnthropic(api_key=settings.api_key)
        self._model = settings.model_conversational
        self.last_usage = None

    def _persona_block(self) -> dict:
        # Stable, cached prefix (>=4096 tokens). Byte-identical in warm() and respond().
        return {"type": "text", "text": self._persona, "cache_control": {"type": "ephemeral"}}

    def _system(self) -> list[dict]:
        memory_text = self._memory.text().strip()
        tail = (f"# 기억\n{memory_text}\n\n" if memory_text else "") + _GUIDANCE
        # Memory/guidance go AFTER the cache breakpoint so the persona prefix stays cached.
        return [self._persona_block(), {"type": "text", "text": tail}]

    async def warm(self) -> None:
        # Pre-warm: non-streaming max_tokens=0 over the same persona prefix.
        await self._client.messages.create(
            model=self._model,
            max_tokens=0,
            system=[self._persona_block()],
            messages=[{"role": "user", "content": "warmup"}],
        )

    async def respond(self, user_text: str) -> AsyncIterator[str]:
        async with self._client.messages.stream(
            model=self._model,
            max_tokens=1024,
            system=self._system(),
            messages=[{"role": "user", "content": user_text}],
        ) as stream:
            async for text in stream.text_stream:
                yield text
            final = await stream.get_final_message()
            self.last_usage = final.usage
