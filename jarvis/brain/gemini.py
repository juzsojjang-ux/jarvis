"""GeminiBrain — Google Gemini 기반 JARVIS 두뇌 어댑터.

Brain 프로토콜(base.py)을 구현한다. 함수호출 루프로 jarvis 도구 30종 실행,
[KO] 자막 분리, 권한 정책 게이트를 모두 처리한다.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from .base import split_ko
from .history import ConversationHistory
from .tool_policy import decide
from ..tools.registry import neutral_tools


def _gemini_key(settings: Any) -> str | None:
    """settings → keyring 순으로 Gemini API 키를 찾아 반환한다. 없으면 None."""
    val = getattr(settings, "gemini_api_key", None)
    if val:
        return val
    try:
        import keyring  # noqa: PLC0415
        val = keyring.get_password("jarvis", "gemini_api_key")
        return val or None
    except Exception:  # noqa: BLE001
        return None


class GeminiBrain:
    """Google Gemini(google-genai 2.8+) 기반 두뇌 어댑터."""

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

        self._model: str = getattr(settings, "gemini_model", "") or "gemini-2.5-flash"

        # Client injection for tests; lazy creation for production.
        if client is not None:
            self._client_instance: Any = client
        elif client_factory is not None:
            self._client_instance = client_factory()
        else:
            self._client_instance = None  # lazy — created on first _client() call

        self._tool_obj: Any = None  # cached types.Tool

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

    def _function_tool(self) -> Any:
        if self._tool_obj is not None:
            return self._tool_obj
        from google.genai import types  # noqa: PLC0415
        decls = [
            types.FunctionDeclaration(
                name=t.name,
                description=t.description,
                parameters_json_schema=t.parameters,
            )
            for t in self._tools
        ]
        self._tool_obj = types.Tool(function_declarations=decls)
        return self._tool_obj

    def _config(self) -> Any:
        from google.genai import types  # noqa: PLC0415
        return types.GenerateContentConfig(
            system_instruction=self._system_prompt(),
            tools=[self._function_tool()],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

    def _config_no_tools(self, system: str) -> Any:
        from google.genai import types  # noqa: PLC0415
        return types.GenerateContentConfig(
            system_instruction=system,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

    def _client(self) -> Any:
        if self._client_instance is not None:
            return self._client_instance
        # Lazy real client creation — key is required here.
        key = _gemini_key(self._settings)
        if not key:
            raise RuntimeError(
                "제미나이 API 키가 없습니다. 첫 실행 설정에서 키를 입력하세요."
            )
        from google import genai  # noqa: PLC0415
        self._client_instance = genai.Client(api_key=key)
        return self._client_instance

    # ------------------------------------------------------------------
    # Brain protocol methods
    # ------------------------------------------------------------------

    async def respond(self, user_text: str) -> AsyncIterator[str]:  # type: ignore[override]
        self.last_subtitle = ""
        final_text = ""
        try:
            from google.genai import types  # noqa: PLC0415

            user_payload = (self._history.as_context() + user_text) if self._history.turns else user_text

            contents: list[Any] = [
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=user_payload)],
                )
            ]

            for _iteration in range(8):
                resp = await self._client().aio.models.generate_content(
                    model=self._model,
                    contents=contents,
                    config=self._config(),
                )

                # Guard empty response.
                try:
                    parts = resp.candidates[0].content.parts
                except (IndexError, AttributeError):
                    break
                if not parts:
                    break

                # Collect function calls and text.
                calls = [
                    (p.function_call.name, dict(p.function_call.args or {}))
                    for p in parts
                    if getattr(p, "function_call", None)
                ]
                text = "".join(
                    p.text for p in parts if getattr(p, "text", None)
                )

                if not calls:
                    # Final text turn — done.
                    final_text = text
                    break

                # Append model turn with function_call parts.
                contents.append(types.Content(role="model", parts=parts))

                # Execute (or deny) each tool call and collect function_response parts.
                response_parts: list[Any] = []
                for name, args in calls:
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
                    response_parts.append(
                        types.Part.from_function_response(
                            name=name, response={"result": result}
                        )
                    )

                contents.append(
                    types.Content(role="user", parts=response_parts)
                )
                # Loop again with function responses fed back.

        except Exception as exc:  # noqa: BLE001
            print(f"[제미나이] 오류: {exc}")
            return

        en, ko = split_ko(final_text or "")
        self.last_subtitle = ko
        self._history.add(user_text, en)
        if en.strip():
            yield en

    async def translate(self, text: str, target_lang: str) -> str:
        """target_lang으로 text를 번역해 반환한다(통역 모드용)."""
        try:
            sys_instr = (
                f"Translate the given text into {target_lang}. "
                "Output ONLY the translation."
            )
            resp = await self._client().aio.models.generate_content(
                model=self._model,
                contents=text,
                config=self._config_no_tools(sys_instr),
            )
            parts = resp.candidates[0].content.parts
            return "".join(p.text for p in parts if getattr(p, "text", None)).strip()
        except Exception:  # noqa: BLE001
            return ""

    async def warm(self) -> None:
        """부팅 예열 — best-effort."""
        try:
            await self._client().aio.models.generate_content(
                model=self._model,
                contents="hi",
                config=self._config_no_tools("Reply 'ok'."),
            )
        except Exception:  # noqa: BLE001
            pass

    async def warm_interpret(self) -> None:
        """Gemini는 영속 세션 없음 — no-op."""
        pass

    async def close(self) -> None:
        """종료 시 리소스 정리."""
        try:
            aio = getattr(self._client_instance, "aio", None)
            if aio is not None:
                close = getattr(aio, "close", None)
                if close is not None:
                    await close()
        except Exception:  # noqa: BLE001
            pass
