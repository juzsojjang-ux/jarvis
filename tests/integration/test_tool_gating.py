import asyncio
from dataclasses import dataclass
from typing import Any

import jarvis.tools.mcp_client as mc
from jarvis.brain.claude import TASK_FILLER, Brain
from jarvis.tools.builtin.local_tools import calc, make_remember_tool
from jarvis.tools.builtin.time_weather import get_time, get_weather
from jarvis.tools.builtin.web_search import WEB_SEARCH_TOOL
from jarvis.tools.registry import ToolRegistry

_PERSONA = "가" * 5000


@dataclass
class TextBlock:
    text: str
    type: str = "text"


@dataclass
class ToolUseBlock:
    id: str
    name: str
    input: dict
    type: str = "tool_use"


@dataclass
class FakeMessage:
    content: list
    stop_reason: str
    usage: Any = None


class _FakeStream:
    def __init__(self, deltas, final):
        self._deltas = deltas
        self._final = final

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    @property
    def text_stream(self):
        async def gen():
            for d in self._deltas:
                yield d

        return gen()

    async def get_final_message(self):
        return self._final


class FakeMessages:
    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.calls = []

    def stream(self, **kwargs):
        # Snapshot messages at call time (the tool loop mutates the shared list).
        recorded = dict(kwargs)
        recorded["messages"] = list(kwargs["messages"])
        self.calls.append(recorded)
        deltas, final = self._scripted.pop(0)
        return _FakeStream(deltas, final)


class FakeAnthropic:
    def __init__(self, scripted):
        self.messages = FakeMessages(scripted)


class FakeMemory:
    def __init__(self):
        self.notes = []

    def text(self):
        return "사용자 이름은 이성재."

    def remember(self, note):
        self.notes.append(note)


@dataclass
class FakeSettings:
    model_task: str = "claude-opus-4-8"
    model_conversational: str = "claude-haiku-4-5"


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

    async def call_tool(self, name, arguments):
        return self._result


class FakeMCPTool:
    def __init__(self, name, description, inputSchema):
        self.name = name
        self.description = description
        self.inputSchema = inputSchema


def _collect(brain, text):
    async def run():
        return [d async for d in brain.respond(text)]

    return asyncio.run(run())


def _registry_with_all_kinds(memory):
    reg = ToolRegistry()
    reg.register(get_time)                 # @beta_async_tool (local, ungated)
    reg.register(get_weather)              # @beta_async_tool (local, ungated)
    reg.register(calc)                     # @beta_async_tool (local, ungated)
    reg.register(make_remember_tool(memory))  # closure-bound local (ungated)
    reg.register(WEB_SEARCH_TOOL)          # server-side dict (non-local)
    mcp_tool = mc.HandRolledMCPTool(       # MCP-wrapped tool (local, gated)
        FakeMCPTool("premiere_add_clip", "타임라인에 클립 추가", {"type": "object"}),
        FakeSession(FakeResult([FakeContent("ok")])),
    )
    reg.register(mcp_tool, gated=True)
    return reg


def test_heterogeneous_tools_coexist():
    reg = _registry_with_all_kinds(FakeMemory())
    defs = reg.tools()
    names = {d.get("name") for d in defs}
    assert {"get_time", "get_weather", "calc", "remember",
            "web_search", "premiere_add_clip"} <= names
    assert {"type": "web_search_20260209", "name": "web_search"} in defs
    assert reg.is_gated("premiere_add_clip") is True
    assert reg.is_gated("get_time") is False
    assert reg.is_gated("web_search") is False


def test_korean_time_request_triggers_tool_and_spoken_answer():
    reg = _registry_with_all_kinds(FakeMemory())
    scripted = [
        (["확인할게요. "], FakeMessage([ToolUseBlock("t1", "get_time", {})], "tool_use")),
        (["지금은 오후 3시입니다."],
         FakeMessage([TextBlock("지금은 오후 3시입니다.")], "end_turn")),
    ]
    client = FakeAnthropic(scripted)
    prompts = []

    async def confirm(prompt):
        prompts.append(prompt)
        return True

    brain = Brain(FakeSettings(), FakeMemory(), _PERSONA, client=client,
                  registry=reg, confirm=confirm)
    out = _collect(brain, "지금 몇 시야?")
    assert out[0] == TASK_FILLER
    assert "오후 3시" in "".join(out)
    assert prompts == []  # get_time is not gated
    tool_result = client.messages.calls[1]["messages"][-1]["content"][0]
    assert tool_result["tool_use_id"] == "t1" and "시" in tool_result["content"]


def test_irreversible_tool_is_voice_gated():
    reg = _registry_with_all_kinds(FakeMemory())
    scripted = [
        ([], FakeMessage([ToolUseBlock("p1", "premiere_add_clip", {"clip": "a"})], "tool_use")),
        (["타임라인에 적용했습니다."],
         FakeMessage([TextBlock("타임라인에 적용했습니다.")], "end_turn")),
    ]
    client = FakeAnthropic(scripted)
    prompts = []

    async def confirm(prompt):
        prompts.append(prompt)
        return True

    brain = Brain(FakeSettings(), FakeMemory(), _PERSONA, client=client,
                  registry=reg, confirm=confirm)
    out = _collect(brain, "프리미어에 클립 추가 실행해줘")
    assert len(prompts) == 1 and "premiere_add_clip" in prompts[0]
    tool_result = client.messages.calls[1]["messages"][-1]["content"][0]
    assert "ok" in tool_result["content"]
    assert out[0] == TASK_FILLER
    assert "".join(out[1:]) == "타임라인에 적용했습니다."


def test_calc_and_remember_end_to_end():
    # Spec acceptance: "3 더하기 5 알려주고 메모해줘" -> calc(=8) + remember, one turn.
    memory = FakeMemory()
    reg = _registry_with_all_kinds(memory)
    scripted = [
        (
            [],
            FakeMessage(
                [
                    ToolUseBlock("c1", "calc", {"expression": "3 + 5"}),
                    ToolUseBlock("r1", "remember", {"note": "3 더하기 5는 8"}),
                ],
                "tool_use",
            ),
        ),
        (["3 더하기 5는 8입니다. 메모했습니다."],
         FakeMessage([TextBlock("3 더하기 5는 8입니다. 메모했습니다.")], "end_turn")),
    ]
    client = FakeAnthropic(scripted)

    async def confirm(prompt):
        return True

    brain = Brain(FakeSettings(), memory, _PERSONA, client=client,
                  registry=reg, confirm=confirm)
    out = _collect(brain, "3 더하기 5 알려주고 메모해줘")
    assert out[0] == TASK_FILLER
    assert "8" in "".join(out)
    assert memory.notes == ["3 더하기 5는 8"]
    results = client.messages.calls[1]["messages"][-1]["content"]
    contents = " ".join(r["content"] for r in results)
    assert "8" in contents and "기억" in contents
