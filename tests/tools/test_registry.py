import asyncio

import pytest
from anthropic import beta_async_tool

from jarvis.tools.registry import NeutralTool, ToolRegistry, neutral_tools


def test_register_local_tool_lists_and_dispatches():
    @beta_async_tool
    async def echo(text: str) -> str:
        """문자열을 그대로 반환합니다.

        Args:
            text: 반환할 문자열.
        """
        return f"echo:{text}"

    reg = ToolRegistry()
    assert reg.register(echo) is None  # contract: register(...) -> None
    names = [d["name"] for d in reg.tools()]
    assert "echo" in names
    assert reg.is_gated("echo") is False
    assert asyncio.run(reg.dispatch("echo", {"text": "hi"})) == "echo:hi"


def test_gated_registration_marks_name():
    @beta_async_tool
    async def danger(path: str) -> str:
        """대상을 영구 삭제합니다.

        Args:
            path: 삭제할 경로.
        """
        return "done"

    reg = ToolRegistry()
    reg.register(danger, gated=True)
    assert reg.is_gated("danger") is True
    assert asyncio.run(reg.dispatch("danger", {"path": "/x"})) == "done"


def test_raw_dict_is_non_local_and_not_dispatchable():
    reg = ToolRegistry()
    d = {"type": "web_search_20260209", "name": "web_search"}
    reg.register(d)
    assert d in reg.tools()
    assert reg.is_gated("web_search") is False
    with pytest.raises(KeyError):
        asyncio.run(reg.dispatch("web_search", {}))


def test_heterogeneous_tools_coexist():
    @beta_async_tool
    async def get_x() -> str:
        """엑스를 반환합니다."""
        return "x"

    reg = ToolRegistry()
    reg.register(get_x)
    reg.register({"type": "web_search_20260209", "name": "web_search"})
    defs = reg.tools()
    assert len(defs) == 2
    assert {d.get("name") for d in defs} == {"get_x", "web_search"}


# ---------------------------------------------------------------------------
# NeutralTool / neutral_tools — Gemini/GPT 공유 레지스트리
# ---------------------------------------------------------------------------

def test_has_47_tools_with_specs():
    tools = neutral_tools(memory=None)
    assert len(tools) == 47  # +create_skill, list_skills(자가 코딩)
    names = {t.name for t in tools}
    assert {"get_time", "send_message", "open_app", "remember", "screen_control",
            "show_panel", "hide_panel", "screen_control_mode", "click_by_name"} <= names
    for t in tools:
        assert isinstance(t.parameters, dict)


def test_call_returns_handler_text():
    tools = {t.name: t for t in neutral_tools()}
    out = asyncio.run(tools["get_time"].call({}))
    assert "시" in out or "년" in out  # Korean date/time string


def test_call_swallows_handler_error():
    async def boom(args):
        raise RuntimeError("x")
    t = NeutralTool("x", "d", {}, boom)
    assert asyncio.run(t.call({})) == "도구 실행에 실패했습니다."


def test_remember_tool_present_with_memory():
    class _Mem:
        def __init__(self): self.saved = []
        def remember(self, note): self.saved.append(note)
    m = _Mem()
    tools = {t.name: t for t in neutral_tools(memory=m)}
    asyncio.run(tools["remember"].call({"note": "테스트"}))
    assert m.saved == ["테스트"]
