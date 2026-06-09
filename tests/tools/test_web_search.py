import asyncio

import pytest

from jarvis.tools.builtin.web_search import IS_LOCAL, WEB_SEARCH_TOOL
from jarvis.tools.registry import ToolRegistry


def test_web_search_tool_is_correct_server_dict():
    assert WEB_SEARCH_TOOL == {"type": "web_search_20260209", "name": "web_search"}
    assert IS_LOCAL is False


def test_web_search_registers_as_non_local():
    reg = ToolRegistry()
    reg.register(WEB_SEARCH_TOOL)
    assert WEB_SEARCH_TOOL in reg.tools()
    assert reg.is_gated("web_search") is False
    with pytest.raises(KeyError):
        asyncio.run(reg.dispatch("web_search", {}))
