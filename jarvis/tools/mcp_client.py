from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from typing import Any

# Startup import-check for the SDK MCP helper. async_mcp_tool signature
# (anthropic==0.107.1): async_mcp_tool(tool, session, *, cache_control=None,
# defer_loading=None, allowed_callers=None, eager_input_streaming=None,
# input_examples=None, strict=None) -> BetaAsyncFunctionTool. If the import
# fails (anthropic[mcp] absent), fall back to a hand-rolled wrapper.
try:  # pragma: no cover - exercised via monkeypatch in tests
    from anthropic.lib.tools.mcp import async_mcp_tool as _async_mcp_tool

    _HAS_MCP_HELPER = True
except Exception:  # noqa: BLE001
    _async_mcp_tool = None
    _HAS_MCP_HELPER = False

# BM25 tool-search tool (a TOOL TYPE, not a beta header). Used together with
# defer_loading=True for many-tool MCP servers.
TOOL_SEARCH_BM25: dict[str, str] = {
    "type": "tool_search_tool_bm25_20251119",
    "name": "tool_search_tool_bm25",
}


@dataclass
class MCPServerConfig:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    defer: bool = False  # many-tool server -> defer_loading + tool search


# Phase-2 stub: premiere-pro MCP server, left DISABLED until Phase 2.
DEFAULT_MCP_SERVERS: list[MCPServerConfig] = [
    MCPServerConfig(
        name="premiere-pro",
        command="node",
        args=["/opt/premiere-mcp/server.js"],
        env={},
        enabled=False,
        defer=True,
    ),
]


class HandRolledMCPTool:
    """Fallback wrapper used when async_mcp_tool is unavailable.

    Exposes the ToolRegistry contract: .name / .to_dict() / async .call().
    """

    def __init__(self, tool: Any, session: Any, *, defer_loading: bool = False) -> None:
        self._tool = tool
        self._session = session
        self._defer = defer_loading
        self.name: str = tool.name

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self._tool.name,
            "description": getattr(self._tool, "description", "") or "",
            "input_schema": getattr(self._tool, "inputSchema", {"type": "object"}),
        }
        if self._defer:
            d["defer_loading"] = True
        return d

    async def call(self, input: Any) -> str:
        result = await self._session.call_tool(self._tool.name, dict(input) if input else {})
        parts: list[str] = []
        for content in getattr(result, "content", None) or []:
            text = getattr(content, "text", None)
            parts.append(text if text is not None else str(content))
        out = "\n".join(parts)
        if getattr(result, "isError", False):
            return f"[MCP 오류] {out}"
        return out


def wrap_mcp_tool(tool: Any, session: Any, *, defer_loading: bool = False) -> Any:
    """Wrap a single MCP tool: SDK helper if present, else hand-rolled."""
    if _HAS_MCP_HELPER:
        return _async_mcp_tool(tool, session, defer_loading=defer_loading or None)
    return HandRolledMCPTool(tool, session, defer_loading=defer_loading)


async def load_mcp_tools(
    servers: list[MCPServerConfig],
    exit_stack: contextlib.AsyncExitStack,
) -> tuple[list[Any], dict[str, str] | None]:
    """Open enabled MCP servers via the exit stack and return wrapped tools.

    Returns (tools, search_tool); search_tool is TOOL_SEARCH_BM25 if any
    enabled server uses defer-loading, else None. mcp is imported lazily so the
    all-disabled path needs no mcp install. The exit_stack is owned by the
    caller and held open for the process lifetime.
    """
    tools: list[Any] = []
    need_search = False
    for cfg in servers:
        if not cfg.enabled:
            continue
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        params = StdioServerParameters(
            command=cfg.command,
            args=list(cfg.args),
            env=dict(cfg.env) or None,
        )
        read, write = await exit_stack.enter_async_context(stdio_client(params))
        session = await exit_stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        listed = await session.list_tools()
        for tool in listed.tools:
            tools.append(wrap_mcp_tool(tool, session, defer_loading=cfg.defer))
        if cfg.defer:
            need_search = True
    return tools, (TOOL_SEARCH_BM25 if need_search else None)
