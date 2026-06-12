from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Callable

# Startup import-check: local tools are produced by @beta_async_tool, whose
# .call() is awaited in dispatch(). This GUARDS the pinned SDK so a missing or
# wrong-version anthropic fails loudly at import time with a clear message.
try:  # pragma: no cover - environment guard
    from anthropic import beta_async_tool as _beta_async_tool  # noqa: F401
except ImportError as exc:  # pragma: no cover - environment guard
    raise ImportError(
        "jarvis.tools.registry requires `beta_async_tool` from anthropic==0.107.1. "
        "Install the pinned SDK: pip install 'anthropic==0.107.1'."
    ) from exc


class ToolRegistry:
    """Holds heterogeneous tools for the TASK path.

    Local tools are objects produced by ``@beta_async_tool`` (or an MCP
    wrapper): they expose ``.name``, ``.to_dict()`` and ``.call()`` and are
    dispatchable locally. Raw/server-side tools (e.g. the web_search dict) are
    plain dicts: they are listed for the API but NOT dispatchable locally and
    are never gated.
    """

    def __init__(self) -> None:
        self._local: dict[str, Any] = {}
        self._raw: list[dict[str, Any]] = []
        self._gated: set[str] = set()

    def register(self, fn: Any, gated: bool = False) -> None:
        """Register a local tool object or a raw server-tool dict.

        ``gated=True`` marks an irreversible local action that must be
        voice-confirmed before dispatch. ``gated`` is ignored for raw dicts.
        """
        if isinstance(fn, dict):
            self._raw.append(fn)
            return
        if not (hasattr(fn, "to_dict") and hasattr(fn, "call") and hasattr(fn, "name")):
            raise TypeError(
                "register() expects a @beta_async_tool object (or MCP wrapper) "
                "with .name/.to_dict()/.call(), or a raw server-tool dict"
            )
        self._local[fn.name] = fn
        if gated:
            self._gated.add(fn.name)

    def tools(self) -> list[dict[str, Any]]:
        """Tool-definition dicts for messages(...) tools=."""
        out: list[dict[str, Any]] = [t.to_dict() for t in self._local.values()]
        out.extend(self._raw)
        return out

    def is_gated(self, name: str) -> bool:
        return name in self._gated

    async def dispatch(self, name: str, args: Any) -> str:
        """Run a local tool by name; raise KeyError for unknown/non-local."""
        if name not in self._local:
            raise KeyError(name)
        result = self._local[name].call(dict(args) if args else {})
        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, str):
            return result
        # Iterable[BetaContent] -> join any text parts.
        parts: list[str] = []
        for block in result:
            text = getattr(block, "text", None)
            if text is None and isinstance(block, dict):
                text = block.get("text")
            parts.append(text if text is not None else str(block))
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# 프로바이더 중립 도구 레지스트리 — Gemini/GPT 함수호출 루프가 jarvis 도구를
# 재사용한다(Claude는 MCP 서버 경로). 같은 SdkMcpTool 객체에서 스펙을 뽑으므로
# 도구 정의가 한 곳(jarvis_mcp)에만 산다.
# ---------------------------------------------------------------------------

@dataclass
class NeutralTool:
    name: str
    description: str
    parameters: dict           # JSON schema (input_schema)
    handler: Callable          # async (args: dict) -> {"content":[{"type":"text","text":str}]}

    async def call(self, args: dict | None) -> str:
        try:
            res = await self.handler(args or {})
        except Exception:  # noqa: BLE001 - 도구는 절대 raise하지 않는다(두뇌에 안내 회신)
            return "도구 실행에 실패했습니다."
        try:
            blocks = (res or {}).get("content", [])
            texts = [b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
            return "".join(texts) or ""
        except Exception:  # noqa: BLE001
            return ""


def neutral_tools(memory: Any = None) -> list[NeutralTool]:
    # 자가 확장 스킬(~/.jarvis/skills)은 build_tool_objects에 합류해 있다 —
    # 여기서 또 더하면 중복 등록된다(클로드 두뇌 누락 버그 고치며 일원화).
    from .jarvis_mcp import build_tool_objects  # local import to avoid circular deps
    out = []
    for t in build_tool_objects(memory):
        out.append(NeutralTool(name=t.name, description=t.description,
                               parameters=getattr(t, "input_schema", {}) or {},
                               handler=t.handler))
    return out
