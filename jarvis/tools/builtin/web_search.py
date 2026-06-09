from __future__ import annotations

# Server-side tool: Anthropic executes the search; the client never dispatches
# it. Latest version (web_search_20260209) supports dynamic filtering on
# claude-opus-4-8. Register the dict via ToolRegistry.register(WEB_SEARCH_TOOL).
WEB_SEARCH_TOOL: dict[str, str] = {
    "type": "web_search_20260209",
    "name": "web_search",
}

# Flag: this tool runs on Anthropic's servers, not locally.
IS_LOCAL: bool = False
