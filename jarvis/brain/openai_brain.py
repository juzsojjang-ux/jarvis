"""GPTBrain — OpenAI Chat Completions 기반 JARVIS 두뇌 어댑터.

Brain 프로토콜(base.py)을 구현한다. 함수호출 루프로 jarvis 도구 30종 실행,
[KO] 자막 분리, 권한 정책 게이트를 모두 처리한다.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from .base import split_ko
from .history import ConversationHistory
from .tool_policy import decide
from ..tools.registry import neutral_tools


def _gpt_key(settings: Any) -> str | None:
    """settings → keyring 순으로 OpenAI API 키를 찾아 반환한다. 없으면 None."""
    val = getattr(settings, "gpt_api_key", None)
    if val:
        return val
    try:
        import keyring  # noqa: PLC0415
        val = keyring.get_password("jarvis", "openai_api_key")
        return val or None
    except Exception:  # noqa: BLE001
        return None


class GPTBrain:
    """OpenAI Chat Completions(openai>=2.0) 기반 두뇌 어댑터."""

    last_subtitle: str
    remote_mode: bool

    def __init__(
        self,
        settings: Any,
        memory: Any,
        persona_text: str,
        *,
        confirm: Any = None,
        client: Any = None,
        client_factory: Any = None,
        history: Any = None,
    ) -> None:
        self.last_subtitle = ""
        self.remote_mode = False
        self._settings = settings
        self._memory = memory
        self._persona = persona_text
        self._confirm = confirm

        self._tools = neutral_tools(memory)
        self._by_name = {t.name: t for t in self._tools}

        self._model: str = getattr(settings, "gpt_model", "") or "gpt-4o"

        # Client injection for tests; lazy creation for production.
        if client is not None:
            self._client_instance: Any = client
        elif client_factory is not None:
            self._client_instance = client_factory()
        else:
            self._client_instance = None  # lazy — created on first _client() call

        self._tools_cache: list[dict] | None = None  # cached OpenAI tools payload

        self._history: ConversationHistory = (
            history if history is not None else ConversationHistory()
        )
        self._history.load()

    # ------------------------------------------------------------------
    # Brain protocol helpers
    # ------------------------------------------------------------------

    def _trust_on(self) -> bool:
        from jarvis.core.control_gate import TRUST_GATE  # noqa: PLC0415
        return TRUST_GATE.is_on()

    def _system_prompt(self) -> str:
        from jarvis.brain.subscription import _guidance_for  # noqa: PLC0415
        memory_text = self._memory.text().strip() if (self._memory is not None and hasattr(self._memory, "text")) else ""
        tail = (f"# 기억\n{memory_text}\n\n" if memory_text else "") + _guidance_for("en")
        return f"{self._persona}\n\n{tail}"

    def _tools_payload(self) -> list[dict]:
        if self._tools_cache is not None:
            return self._tools_cache
        self._tools_cache = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self._tools
        ]
        return self._tools_cache

    def _client(self) -> Any:
        if self._client_instance is not None:
            return self._client_instance
        # Lazy real client creation — key is required here.
        key = _gpt_key(self._settings)
        if not key:
            raise RuntimeError(
                "OpenAI API 키가 없습니다. 첫 실행 설정에서 키를 입력하세요."
            )
        from openai import AsyncOpenAI  # noqa: PLC0415
        self._client_instance = AsyncOpenAI(api_key=key)
        return self._client_instance

    # ------------------------------------------------------------------
    # Brain protocol methods
    # ------------------------------------------------------------------

    async def respond(self, user_text: str) -> AsyncIterator[str]:  # type: ignore[override]
        self.last_subtitle = ""
        final_text = ""
        try:
            user_payload = (self._history.as_context() + user_text) if self._history.turns else user_text
            messages: list[dict] = [
                {"role": "system", "content": self._system_prompt()},
                {"role": "user", "content": user_payload},
            ]

            for _iteration in range(8):
                resp = await self._client().chat.completions.create(
                    model=self._model,
                    messages=messages,
                    tools=self._tools_payload(),
                    tool_choice="auto",
                )
                msg = resp.choices[0].message

                if not msg.tool_calls:
                    # Final text turn — done.
                    final_text = msg.content or ""
                    break

                # Append assistant message with tool_calls to messages.
                messages.append({
                    "role": "assistant",
                    "content": msg.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in msg.tool_calls
                    ],
                })

                # Execute (or deny) each tool call and collect tool messages.
                for tc in msg.tool_calls:
                    name = tc.function.name
                    try:
                        args = json.loads(tc.function.arguments)
                    except Exception:  # noqa: BLE001
                        args = {}

                    ok, reason = await decide(
                        name,
                        args,
                        remote_mode=self.remote_mode,
                        trust_on=self._trust_on(),
                        confirm=self._confirm,
                    )
                    if ok and name in self._by_name:
                        result = await self._by_name[name].call(args)
                    else:
                        result = reason or "알 수 없는 도구입니다."

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    })
                # Loop again with tool responses fed back.

        except Exception as exc:  # noqa: BLE001
            print(f"[GPT] 오류: {exc}")
            return

        en, ko = split_ko(final_text or "")
        self.last_subtitle = ko
        self._history.add(user_text, en)
        if en.strip():
            yield en

    async def translate(self, text: str, target_lang: str) -> str:
        """target_lang으로 text를 번역해 반환한다(통역 모드용)."""
        try:
            resp = await self._client().chat.completions.create(
                model=self._model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            f"Translate the given text into {target_lang}. "
                            "Output ONLY the translation."
                        ),
                    },
                    {"role": "user", "content": text},
                ],
            )
            return (resp.choices[0].message.content or "").strip()
        except Exception:  # noqa: BLE001
            return ""

    async def warm(self) -> None:
        """부팅 예열 — best-effort."""
        try:
            await self._client().chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": "Reply 'ok'."},
                    {"role": "user", "content": "hi"},
                ],
            )
        except Exception:  # noqa: BLE001
            pass

    async def warm_interpret(self) -> None:
        """GPT는 영속 세션 없음 — no-op."""
        pass

    async def close(self) -> None:
        """종료 시 리소스 정리."""
        try:
            await self._client().close()
        except Exception:  # noqa: BLE001
            pass
