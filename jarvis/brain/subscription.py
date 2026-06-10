"""JARVIS brain on the Claude SUBSCRIPTION (no Anthropic API key, no per-token bill).

Routes through claude-agent-sdk, which runs the bundled Claude Code engine and
authenticates with the user's logged-in Claude Pro/Max plan — inference is covered by
the subscription, not the paid API. Exposes the Orchestrator contract (`respond()`
async text stream + `warm()`).

LATENCY: a persistent ClaudeSDKClient stays connected across turns (the one-shot
query() helper cold-starts the CLI every utterance — seconds of dead air). With
include_partial_messages, text deltas stream out as they are generated, so the voice
pipeline starts speaking the first sentence before the answer finishes.

Hardening: ANTHROPIC_API_KEY is stripped from the child env (so it can never silently
fall back to paid API billing); the agent is isolated from the host Claude Code project
(`setting_sources=[]` → no CLAUDE.md/hooks/skills leak in) and conversational
(`allowed_tools=[]`, `max_turns=1`) so a spoken sentence can't trigger Bash/file edits.
"""
from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any

# Voice-optimized guidance. Short, spoken-style, NO markdown (lists read awful via TTS
# and make answers slow). The user may speak Korean either way; reply_language controls
# what JARVIS SAYS (Pocket TTS is English-only).
_GUIDANCE_KO = (
    "너는 자비스, 음성으로 답하는 한국어 집사다. 반드시 한두 문장으로 짧게, "
    "목록·번호·마크다운·별표 같은 기호 없이 사람이 말하듯 자연스럽게 답하라. "
    "사고 과정·머리말·맺음말 없이 핵심만 먼저 말하라. 내용이 길어질 것 같으면 "
    "가장 중요한 한 가지만 말하고 '더 알려드릴까요?'처럼 짧게 물어라. "
    "시간·날씨·앱 실행·볼륨 조절·기억은 네게 주어진 도구로 직접 처리하고, 최신 정보는 "
    "웹 검색으로 확인하라. 도구를 쓸 수 있으면 되묻지 말고 바로 실행한 뒤 결과만 짧게 알려라."
)
_GUIDANCE_EN = (
    "You are JARVIS, Tony Stark's refined British AI butler. The user may speak Korean, "
    "but you ALWAYS reply in ENGLISH. Keep it to one or two short, natural spoken "
    "sentences — no markdown, lists, numbering, or symbols, no preamble or sign-off. "
    "Address the user as 'sir'. Use the signature JARVIS manner: dry, understated wit and "
    "the occasional subtle, polite quip — clever, never goofy, and never at the expense "
    "of being helpful. Use your tools directly for time, weather, opening apps, volume, "
    "and memory, and web search for current info; when a tool applies, act first and "
    "state the result briefly — don't ask. "
    "After your spoken English reply, append on a new line exactly '[KO] ' followed by a "
    "natural Korean translation of what you said, for on-screen subtitles."
)
_GUIDANCE = _GUIDANCE_KO  # back-compat alias (tests/imports)


def _guidance_for(reply_language: str) -> str:
    return _GUIDANCE_EN if str(reply_language).lower().startswith("en") else _GUIDANCE_KO


class SubscriptionBrain:
    def __init__(
        self,
        settings: Any,
        memory: Any,
        persona_text: str,
        *,
        client_cls: Any = None,
        options_cls: Any = None,
        assistant_message: Any = None,
        stream_event: Any = None,
    ) -> None:
        self._settings = settings
        self._memory = memory
        self._persona = persona_text  # real >=4096-token persona
        self._client_cls = client_cls
        self._options_cls = options_cls
        self._assistant_message = assistant_message
        self._stream_event = stream_event
        self._client: Any = None
        self.last_subtitle = ""  # Korean subtitle of the last reply (for the HUD)

    def _ensure_sdk(self) -> None:
        if self._client_cls and self._options_cls and self._assistant_message:
            return
        try:
            from claude_agent_sdk import (
                AssistantMessage,
                ClaudeAgentOptions,
                ClaudeSDKClient,
                StreamEvent,
            )
        except Exception as exc:  # noqa: BLE001
            raise ImportError(
                "구독 로그인 두뇌에는 claude-agent-sdk가 필요합니다. "
                "설치: pip install claude-agent-sdk · 그리고 'claude' 로그인 필요 "
                "(API 키 없이 구독으로 동작)."
            ) from exc
        self._client_cls = self._client_cls or ClaudeSDKClient
        self._options_cls = self._options_cls or ClaudeAgentOptions
        self._assistant_message = self._assistant_message or AssistantMessage
        self._stream_event = self._stream_event or StreamEvent

    def _system_prompt(self) -> str:
        memory_text = self._memory.text().strip() if self._memory is not None else ""
        guidance = _guidance_for(getattr(self._settings, "reply_language", "ko"))
        tail = (f"# 기억\n{memory_text}\n\n" if memory_text else "") + guidance
        return f"{self._persona}\n\n{tail}"

    def _options(self) -> Any:
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        # JARVIS capabilities: read-only web tools (current events) + safe in-process
        # action tools (time/weather/open-app/volume/remember). Bash/file-edit stay
        # forbidden — a spoken sentence can never run a command or touch the disk.
        from jarvis.tools.jarvis_mcp import JARVIS_TOOL_NAMES, build_jarvis_mcp_server
        kw: dict[str, Any] = dict(
            system_prompt=self._system_prompt(),
            allowed_tools=["WebSearch", "WebFetch", *JARVIS_TOOL_NAMES],
            disallowed_tools=["Bash", "Edit", "Write", "NotebookEdit"],
            mcp_servers={"jarvis": build_jarvis_mcp_server(self._memory)},
            setting_sources=[],    # isolate from the host Claude Code project
            max_turns=4,           # allow a tool round-trip; cap over-searching
            max_thinking_tokens=0,  # snappy voice replies — no extended thinking latency
            env=env,
            include_partial_messages=True,   # stream text deltas -> speak early
        )
        model = getattr(self._settings, "subscription_model", "") or ""
        if model:
            kw["model"] = model
        return self._options_cls(**kw)

    async def _ensure_client(self) -> Any:
        self._ensure_sdk()
        if self._client is None:
            client = self._client_cls(options=self._options())
            await client.connect()
            self._client = client
        return self._client

    # Spoken the instant a web search starts, so there's no dead air while the search
    # + synthesis run (the slow part of a current-events answer).
    TOOL_FILLER = "잠시만요, 확인하겠습니다."
    TOOL_FILLER_EN = "One moment, sir."

    def _tool_filler(self) -> str:
        lang = getattr(self._settings, "reply_language", "ko")
        return self.TOOL_FILLER_EN if str(lang).lower().startswith("en") else self.TOOL_FILLER

    @staticmethod
    def _delta_text(event: Any) -> str:
        """Extract a text delta from a raw StreamEvent (anything else -> '')."""
        raw = getattr(event, "event", None) or {}
        if raw.get("type") == "content_block_delta":
            delta = raw.get("delta") or {}
            if delta.get("type") == "text_delta":
                return delta.get("text") or ""
        return ""

    @staticmethod
    def _is_tool_start(event: Any) -> bool:
        # Filler only for the SLOW web tools; instant local actions (open_app, volume)
        # don't need a "잠시만요".
        raw = getattr(event, "event", None) or {}
        if raw.get("type") == "content_block_start":
            b = raw.get("content_block") or {}
            if b.get("type") == "server_tool_use":
                return True
            if b.get("type") == "tool_use":
                return b.get("name", "") in ("WebSearch", "WebFetch")
        return False

    KO_MARK = "[KO]"

    async def respond(self, user_text: str) -> AsyncIterator[str]:
        client = await self._ensure_client()
        await client.query(user_text)
        # last_subtitle = the Korean translation after the '[KO]' marker; the orchestrator
        # shows it under SPEAKING while the English audio plays. Only the English (before
        # the marker) is ever yielded for speech.
        self.last_subtitle = ""
        streamed = False
        filler_sent = False
        in_ko = False
        pending = ""  # buffer so a '[KO]' marker split across deltas is never spoken
        keep = len(self.KO_MARK) - 1
        async for msg in client.receive_response():
            if self._stream_event is not None and isinstance(msg, self._stream_event):
                if not filler_sent and self._is_tool_start(msg):
                    filler_sent = True
                    yield self._tool_filler()
                text = self._delta_text(msg)
                if not text:
                    continue
                streamed = True
                if in_ko:
                    self.last_subtitle += text
                    continue
                pending += text
                mark = pending.find(self.KO_MARK)
                if mark != -1:
                    before, in_ko = pending[:mark], True
                    self.last_subtitle = pending[mark + len(self.KO_MARK):]
                    pending = ""
                    if before:
                        yield before
                    continue
                if len(pending) > keep:           # hold back a possible marker prefix
                    emit, pending = pending[:-keep], pending[-keep:]
                    if emit:
                        yield emit
            elif isinstance(msg, self._assistant_message) and not streamed:
                full = "".join(getattr(b, "text", "") or ""
                               for b in (getattr(msg, "content", None) or []))
                spoken, _, ko = full.partition(self.KO_MARK)
                self.last_subtitle = ko.strip()
                if spoken.strip():
                    yield spoken
        if not in_ko and pending:
            yield pending
        self.last_subtitle = self.last_subtitle.strip()

    async def warm(self) -> None:
        # Connect the persistent session now so the first turn pays no CLI start-up.
        await self._ensure_client()

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception:  # noqa: BLE001
                pass
            self._client = None
