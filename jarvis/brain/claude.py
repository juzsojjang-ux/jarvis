from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from anthropic import AsyncAnthropic

# Final-answer-only guidance — MUST be present on BOTH the conversational
# (Haiku) and task (Opus) paths. Korean: speak only the final answer, no
# preamble/reasoning/meta. (Identical to M1 so tests/test_brain.py stays green.)
_GUIDANCE = (
    "너는 자비스, 음성으로 답하는 한국어 집사다. 최종적으로 말할 한국어 답변만 출력하라. "
    "사고 과정, 머리말, 맺음말, '음' 같은 군더더기 없이 핵심부터 간결하게 답하라."
)

# Spoken filler emitted before the multi-second Opus turn (spec 6.4 / 9.4).
TASK_FILLER = "잠시만요."

# Keyword heuristic router: a real-world action or a fact that needs a tool
# takes the TASK path (opus + tools); everything else converses on Haiku.
_TASK_KEYWORDS: tuple[str, ...] = (
    "시간", "몇 시", "지금 몇", "날씨", "기온", "온도",
    "검색", "찾아", "뉴스", "주가", "환율", "일정", "예약",
    "실행", "열어", "켜", "꺼", "삭제", "보내", "추가", "편집",
    "계산", "더하기", "빼기", "곱하기", "나누기", "메모", "기억해", "저장",
    "time", "weather", "search", "news",
)

_MAX_TOOL_ITERATIONS = 8


def route(user_text: str) -> str:
    """Return 'task' or 'conversational' from a keyword heuristic."""
    text = user_text.strip()
    return "task" if any(k in text for k in _TASK_KEYWORDS) else "conversational"


class Brain:
    """Streams Claude responses: conversational path (M1) + manual gated tool loop (M3).

    Conversational (Haiku) and TASK (Opus) paths both use a two-block system
    prompt — [persona, cache_control ephemeral] then [memory + final-answer-only
    guidance, NO cache_control] — so memory/guidance changes never bust the
    cached persona prefix. The TASK path emits a short ``잠시만요`` filler, then
    drives claude-opus-4-8 with adaptive thinking + high effort through a manual
    streaming tool loop: it detects tool_use blocks, voice-confirms gated
    (irreversible) tools via the injected ``confirm`` callback before dispatch,
    feeds tool_result blocks back, and re-streams until the model stops.
    """

    def __init__(
        self,
        settings: Any,
        memory: Any,
        persona_text: str,
        client: AsyncAnthropic | None = None,
        *,
        registry: Any = None,
        confirm: Callable[[str], Awaitable[bool]] | None = None,
    ) -> None:
        self._settings = settings
        self._memory = memory
        self._persona = persona_text  # real >=4096-token persona; NO empty fallback
        self._client = client or AsyncAnthropic(api_key=settings.api_key)
        self._registry = registry
        self._confirm = confirm
        self.last_usage = None

    # ----- system prompt (two blocks: cached persona, then uncached memory+guidance) -----
    def _persona_block(self) -> dict[str, Any]:
        # Stable cached prefix (>=4096 tokens). Byte-identical in warm() and respond().
        return {"type": "text", "text": self._persona, "cache_control": {"type": "ephemeral"}}

    def _system(self) -> list[dict[str, Any]]:
        memory_text = self._memory.text().strip() if self._memory is not None else ""
        tail = (f"# 기억\n{memory_text}\n\n" if memory_text else "") + _GUIDANCE
        # Memory/guidance go AFTER the cache breakpoint so the persona stays cached.
        return [self._persona_block(), {"type": "text", "text": tail}]

    async def warm(self) -> None:
        # Pre-warm: persona 프리픽스 캐시를 데운다. max_tokens는 1 이상이어야 한다 — 0이면
        # Anthropic API가 400으로 거부해 예열이 매번 실패했다(audit low). 예열 실패는 무해하게
        # 흡수(subscription.warm과 동일).
        try:
            await self._client.messages.create(
                model=self._settings.model_conversational,
                max_tokens=1,
                system=[self._persona_block()],
                messages=[{"role": "user", "content": "warmup"}],
            )
        except Exception:  # noqa: BLE001 - 예열 실패는 무해
            pass

    async def respond(self, user_text: str) -> AsyncIterator[str]:
        if route(user_text) == "conversational":
            async for delta in self._conversational(user_text):
                yield delta
        else:
            async for delta in self._task(user_text):
                yield delta

    async def _conversational(self, user_text: str) -> AsyncIterator[str]:
        # Haiku: no thinking, no effort, no tools. Final spoken answer only.
        async with self._client.messages.stream(
            model=self._settings.model_conversational,
            max_tokens=1024,
            system=self._system(),
            messages=[{"role": "user", "content": user_text}],
        ) as stream:
            async for text in stream.text_stream:
                yield text
            final = await stream.get_final_message()
            self.last_usage = getattr(final, "usage", None)

    async def _task(self, user_text: str) -> AsyncIterator[str]:
        # Spoken filler BEFORE the slow Opus turn (spec 6.4 / 9.4).
        yield TASK_FILLER
        tools = self._registry.tools() if self._registry is not None else []
        messages: list[dict[str, Any]] = [{"role": "user", "content": user_text}]
        for _ in range(_MAX_TOOL_ITERATIONS):
            async with self._client.messages.stream(
                model=self._settings.model_task,
                max_tokens=2048,
                system=self._system(),
                tools=tools,
                thinking={"type": "adaptive"},
                output_config={"effort": "high"},
                messages=messages,
            ) as stream:
                async for text in stream.text_stream:
                    yield text
                final = await stream.get_final_message()
            self.last_usage = getattr(final, "usage", None)

            # Preserve the full assistant turn (incl. thinking blocks).
            messages.append({"role": "assistant", "content": final.content})

            if final.stop_reason == "pause_turn":
                # Server tool still running; resend without a tool_result.
                continue

            tool_uses = [b for b in final.content if getattr(b, "type", None) == "tool_use"]
            if not tool_uses:
                return

            results: list[dict[str, Any]] = []
            for block in tool_uses:
                results.append(await self._run_tool(block))
            messages.append({"role": "user", "content": results})

    async def _run_tool(self, block: Any) -> dict[str, Any]:
        name = block.name
        tool_use_id = block.id
        args = block.input or {}
        if self._registry.is_gated(name):
            approved = False
            if self._confirm is not None:
                approved = await self._confirm(self._confirm_prompt(name, args))
            if not approved:
                return {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": "사용자가 이 작업의 실행을 취소했습니다.",
                }
        try:
            output = await self._registry.dispatch(name, args)
        except Exception as exc:  # noqa: BLE001
            return {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": f"도구 실행 오류: {exc}",
                "is_error": True,
            }
        return {"type": "tool_result", "tool_use_id": tool_use_id, "content": output}

    @staticmethod
    def _confirm_prompt(name: str, args: Any) -> str:
        return f"'{name}' 작업을 실행할까요? 입력값은 {args} 입니다."
