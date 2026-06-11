"""GPTBrain — OpenAI Chat Completions / Responses API 기반 JARVIS 두뇌 어댑터.

Brain 프로토콜(base.py)을 구현한다. 함수호출 루프로 jarvis 도구 30종 실행,
[KO] 자막 분리, 권한 정책 게이트를 모두 처리한다.

두 가지 동작 모드:
  api_key        — Chat Completions (기존 유료 키 경로, 변경 없음)
  subscription   — Responses API (ChatGPT 구독, codex login 토큰)
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
    """OpenAI Chat Completions / Responses API 기반 두뇌 어댑터."""

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

        # 인증 모드 및 구독 경로 파라미터
        self._auth_mode: str = getattr(settings, "gpt_auth", "subscription") or "subscription"
        self._sub_base: str = (
            getattr(settings, "gpt_subscription_base_url", "")
            or "https://chatgpt.com/backend-api/codex"
        )
        self._sub_model: str = (
            getattr(settings, "gpt_subscription_model", "") or "gpt-5.5"
        )

        # Client injection for tests; lazy creation for production.
        if client is not None:
            self._client_instance: Any = client
        elif client_factory is not None:
            self._client_instance = client_factory()
        else:
            self._client_instance = None  # lazy — created on first _ensure_client() call

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
        """Chat Completions 형식 도구 목록."""
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

    def _responses_tools(self) -> list[dict]:
        """Responses API 형식 도구 목록 (평면 function)."""
        return [
            {
                "type": "function",
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            }
            for t in self._tools
        ]

    def _client(self) -> Any:
        """동기 접근자 — 이미 생성된 클라이언트를 반환한다. 테스트 전용."""
        if self._client_instance is not None:
            return self._client_instance
        # Lazy real client creation (api_key 모드 전용 — subscription은 _ensure_client 사용)
        key = _gpt_key(self._settings)
        if not key:
            raise RuntimeError(
                "OpenAI API 키가 없습니다. 첫 실행 설정에서 키를 입력하세요."
            )
        from openai import AsyncOpenAI  # noqa: PLC0415
        self._client_instance = AsyncOpenAI(api_key=key)
        return self._client_instance

    async def _ensure_client(self) -> Any:
        """비동기 클라이언트 보장 — 없으면 모드에 맞게 생성한다."""
        if self._client_instance is not None:
            return self._client_instance
        if self._auth_mode == "subscription":
            from jarvis.brain.codex_auth import get_access  # noqa: PLC0415
            from openai import AsyncOpenAI  # noqa: PLC0415
            token, acct = await get_access()
            self._client_instance = AsyncOpenAI(
                base_url=self._sub_base,
                api_key=token,
                default_headers={"ChatGPT-Account-Id": acct},
            )
        else:
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
        client = await self._ensure_client()
        user_payload = (
            (self._history.as_context() + user_text) if self._history.turns else user_text
        )
        if self._auth_mode == "subscription":
            async for chunk in self._run_responses(client, user_payload, user_text):
                yield chunk
        else:
            async for chunk in self._run_chat(client, user_payload, user_text):
                yield chunk

    async def _run_chat(
        self, client: Any, user_payload: str, user_text: str
    ) -> AsyncIterator[str]:
        """Chat Completions 도구 루프 (api_key 모드)."""
        final_text = ""
        try:
            messages: list[dict] = [
                {"role": "system", "content": self._system_prompt()},
                {"role": "user", "content": user_payload},
            ]

            for _iteration in range(8):
                resp = await client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    tools=self._tools_payload(),
                    tool_choice="auto",
                )
                msg = resp.choices[0].message

                if not msg.tool_calls:
                    final_text = msg.content or ""
                    break

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

        except Exception as exc:  # noqa: BLE001
            print(f"[GPT] 오류: {exc}")
            return

        en, ko = split_ko(final_text or "")
        self.last_subtitle = ko
        self._history.add(user_text, en)
        if en.strip():
            yield en

    async def _run_responses(
        self, client: Any, user_payload: str, user_text: str
    ) -> AsyncIterator[str]:
        """Responses API 도구 루프 (subscription 모드)."""
        final_text = ""
        try:
            input_items: list[Any] = [{"role": "user", "content": user_payload}]
            tools = self._responses_tools()

            for _iteration in range(8):
                resp = await client.responses.create(
                    model=self._sub_model,
                    instructions=self._system_prompt(),
                    input=input_items,
                    tools=tools,
                    tool_choice="auto",
                )

                # function_call 항목 수집
                calls = [
                    item for item in (resp.output or [])
                    if getattr(item, "type", None) == "function_call"
                ]

                # 텍스트 추출 — output_text 단축키 우선, 없으면 output 파싱
                raw_text: str = getattr(resp, "output_text", None) or ""
                if not raw_text:
                    for item in (resp.output or []):
                        if getattr(item, "type", None) == "message":
                            for part in (getattr(item, "content", None) or []):
                                if getattr(part, "type", None) in ("output_text", "text"):
                                    raw_text += getattr(part, "text", "") or ""

                if not calls:
                    final_text = raw_text
                    break

                # 각 function call 처리
                for item in calls:
                    name = item.name
                    raw_args = item.arguments  # JSON 문자열
                    call_id = item.call_id
                    try:
                        args = json.loads(raw_args)
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

                    # function_call 항목을 dict로 변환하여 input에 추가
                    input_items.append({
                        "type": "function_call",
                        "name": name,
                        "arguments": raw_args,
                        "call_id": call_id,
                    })
                    input_items.append({
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": result,
                    })

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
        client = await self._ensure_client()
        try:
            if self._auth_mode == "subscription":
                resp = await client.responses.create(
                    model=self._sub_model,
                    instructions=(
                        f"Translate the given text into {target_lang}. "
                        "Output ONLY the translation."
                    ),
                    input=[{"role": "user", "content": text}],
                )
                return (getattr(resp, "output_text", "") or "").strip()
            else:
                resp = await client.chat.completions.create(
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
            client = await self._ensure_client()
            if self._auth_mode == "subscription":
                await client.responses.create(
                    model=self._sub_model,
                    instructions="Reply 'ok'.",
                    input=[{"role": "user", "content": "hi"}],
                )
            else:
                await client.chat.completions.create(
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
            if self._client_instance is not None:
                await self._client_instance.close()
        except Exception:  # noqa: BLE001
            pass
