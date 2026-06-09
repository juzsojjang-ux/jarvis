"""JARVIS brain on the Claude SUBSCRIPTION (no Anthropic API key, no per-token bill).

Routes through claude-agent-sdk, which runs the bundled Claude Code engine and
authenticates with the user's logged-in Claude Pro/Max plan (`claude` login) — the
same login the user already uses. So inference is covered by the subscription, not the
paid API. Exposes the exact interface the Orchestrator needs (`respond()` async text
stream + `warm()`), so it drops in for the API Brain with no pipeline changes.

Hardening: ANTHROPIC_API_KEY is stripped from the child env (so it can never silently
fall back to paid API billing); the agent is isolated from the host Claude Code project
(`setting_sources=[]` → no CLAUDE.md/hooks/skills leak in) and conversational
(`allowed_tools=[]`, `max_turns=1`) so a spoken sentence can't trigger Bash/file edits.
"""
from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any

# Kept in sync with jarvis.brain.claude._GUIDANCE, but defined locally so this backend
# imports without pulling in the anthropic API client.
_GUIDANCE = (
    "너는 자비스, 음성으로 답하는 한국어 집사다. 최종적으로 말할 한국어 답변만 출력하라. "
    "사고 과정, 머리말, 맺음말, '음' 같은 군더더기 없이 핵심부터 간결하게 답하라."
)


class SubscriptionBrain:
    def __init__(
        self,
        settings: Any,
        memory: Any,
        persona_text: str,
        *,
        query: Any = None,
        options_cls: Any = None,
        assistant_message: Any = None,
    ) -> None:
        self._settings = settings
        self._memory = memory
        self._persona = persona_text  # real >=4096-token persona
        self._query = query
        self._options_cls = options_cls
        self._assistant_message = assistant_message

    def _ensure_sdk(self) -> None:
        if self._query and self._options_cls and self._assistant_message:
            return
        try:
            from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, query
        except Exception as exc:  # noqa: BLE001
            raise ImportError(
                "구독 로그인 두뇌에는 claude-agent-sdk가 필요합니다. "
                "설치: pip install claude-agent-sdk · 그리고 'claude' 로그인 필요 "
                "(API 키 없이 구독으로 동작)."
            ) from exc
        self._query = self._query or query
        self._options_cls = self._options_cls or ClaudeAgentOptions
        self._assistant_message = self._assistant_message or AssistantMessage

    def _system_prompt(self) -> str:
        memory_text = self._memory.text().strip() if self._memory is not None else ""
        tail = (f"# 기억\n{memory_text}\n\n" if memory_text else "") + _GUIDANCE
        return f"{self._persona}\n\n{tail}"

    def _options(self) -> Any:
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        kw: dict[str, Any] = dict(
            system_prompt=self._system_prompt(),
            allowed_tools=[],      # conversational: never run Bash/file tools from speech
            setting_sources=[],    # isolate from the host Claude Code project
            max_turns=1,
            env=env,
        )
        model = getattr(self._settings, "subscription_model", "") or ""
        if model:
            kw["model"] = model
        return self._options_cls(**kw)

    async def respond(self, user_text: str) -> AsyncIterator[str]:
        self._ensure_sdk()
        async for msg in self._query(prompt=user_text, options=self._options()):
            if isinstance(msg, self._assistant_message):
                for block in getattr(msg, "content", None) or []:
                    text = getattr(block, "text", None)
                    if text:
                        yield text

    async def warm(self) -> None:
        # Fail fast if the SDK/login is missing; the first real turn pays CLI startup.
        self._ensure_sdk()
