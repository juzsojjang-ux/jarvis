import asyncio
import contextlib

import jarvis.tools.mcp_client as mc


class FakeContent:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class FakeResult:
    def __init__(self, content, isError=False):
        self.content = content
        self.isError = isError


class FakeSession:
    def __init__(self, result):
        self._result = result
        self.calls = []

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return self._result


class FakeMCPTool:
    def __init__(self, name, description, inputSchema):
        self.name = name
        self.description = description
        self.inputSchema = inputSchema


def test_handrolled_to_dict_and_call_maps_text_content():
    tool = FakeMCPTool("do_thing", "설명", {"type": "object", "properties": {}})
    sess = FakeSession(FakeResult([FakeContent("결과A"), FakeContent("결과B")]))
    w = mc.HandRolledMCPTool(tool, sess)
    d = w.to_dict()
    assert d["name"] == "do_thing"
    assert d["description"] == "설명"
    assert d["input_schema"] == {"type": "object", "properties": {}}
    assert "defer_loading" not in d
    assert asyncio.run(w.call({"a": 1})) == "결과A\n결과B"
    assert sess.calls == [("do_thing", {"a": 1})]


def test_handrolled_error_result_is_flagged():
    tool = FakeMCPTool("t", "d", {"type": "object"})
    sess = FakeSession(FakeResult([FakeContent("boom")], isError=True))
    w = mc.HandRolledMCPTool(tool, sess)
    assert asyncio.run(w.call({})).startswith("[MCP 오류]")


def test_handrolled_defer_loading_flag():
    tool = FakeMCPTool("t", "d", {"type": "object"})
    w = mc.HandRolledMCPTool(tool, FakeSession(FakeResult([])), defer_loading=True)
    assert w.to_dict()["defer_loading"] is True


def test_wrap_uses_handrolled_when_helper_absent(monkeypatch):
    monkeypatch.setattr(mc, "_HAS_MCP_HELPER", False)
    tool = FakeMCPTool("t", "d", {"type": "object"})
    w = mc.wrap_mcp_tool(tool, FakeSession(FakeResult([])))
    assert isinstance(w, mc.HandRolledMCPTool)


def test_premiere_stub_disabled_and_search_tool_constant():
    by_name = {s.name: s for s in mc.DEFAULT_MCP_SERVERS}
    assert "premiere-pro" in by_name
    assert by_name["premiere-pro"].enabled is False
    assert by_name["premiere-pro"].defer is True
    assert mc.TOOL_SEARCH_BM25 == {
        "type": "tool_search_tool_bm25_20251119",
        "name": "tool_search_tool_bm25",
    }


def test_load_mcp_tools_skips_disabled_servers():
    async def run():
        async with contextlib.AsyncExitStack() as stack:
            return await mc.load_mcp_tools(mc.DEFAULT_MCP_SERVERS, stack)

    tools, search = asyncio.run(run())
    assert tools == []
    assert search is None
