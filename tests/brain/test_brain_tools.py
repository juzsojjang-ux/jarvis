import asyncio
from dataclasses import dataclass
from typing import Any

from anthropic import beta_async_tool

from jarvis.brain.claude import TASK_FILLER, Brain, route
from jarvis.tools.builtin.time_weather import get_time
from jarvis.tools.registry import ToolRegistry

_PERSONA = "가" * 5000  # stand-in for the real >=4096-token cached persona prefix


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
        # Snapshot messages at call time: the tool loop mutates the shared list
        # (the real client serializes the request at the call boundary).
        recorded = dict(kwargs)
        recorded["messages"] = list(kwargs["messages"])
        self.calls.append(recorded)
        deltas, final = self._scripted.pop(0)
        return _FakeStream(deltas, final)


class FakeAnthropic:
    def __init__(self, scripted):
        self.messages = FakeMessages(scripted)


class FakeMemory:
    def text(self):
        return "사용자 이름은 이성재."


@dataclass
class FakeSettings:
    model_task: str = "claude-opus-4-8"
    model_conversational: str = "claude-haiku-4-5"


def _collect(brain, text):
    async def run():
        return [d async for d in brain.respond(text)]

    return asyncio.run(run())


def test_route_keyword_heuristic():
    assert route("지금 몇 시야?") == "task"
    assert route("날씨 알려줘") == "task"
    assert route("뉴스 검색해줘") == "task"
    assert route("3 더하기 5 알려주고 메모해줘") == "task"
    assert route("안녕 오늘 기분 어때?") == "conversational"
    assert route("고마워") == "conversational"


def test_conversational_path_uses_haiku_two_block_cache_no_tools():
    scripted = [(["안녕하세요!"], FakeMessage([TextBlock("안녕하세요!")], "end_turn"))]
    client = FakeAnthropic(scripted)

    async def confirm(prompt):
        return True

    brain = Brain(FakeSettings(), FakeMemory(), _PERSONA, client=client, confirm=confirm)
    out = _collect(brain, "안녕")
    assert "".join(out) == "안녕하세요!"
    kw = client.messages.calls[0]
    assert kw["model"] == "claude-haiku-4-5"
    assert "tools" not in kw
    assert "thinking" not in kw
    assert "output_config" not in kw
    # Two-block system: cached persona prefix, then uncached memory+guidance.
    assert kw["system"][0]["text"] == _PERSONA
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in kw["system"][1]
    assert "이성재" in kw["system"][1]["text"]   # memory present
    assert "최종" in kw["system"][1]["text"]      # final-answer-only guidance present


def test_task_path_emits_voice_filler_before_opus_turn():
    scripted = [
        (["답입니다."], FakeMessage([TextBlock("답입니다.")], "end_turn")),
    ]
    client = FakeAnthropic(scripted)

    async def confirm(prompt):
        return True

    brain = Brain(FakeSettings(), FakeMemory(), _PERSONA, client=client,
                  registry=ToolRegistry(), confirm=confirm)
    out = _collect(brain, "지금 몇 시야?")
    assert out[0] == TASK_FILLER          # filler spoken FIRST, before the slow turn
    assert "".join(out[1:]) == "답입니다."


def test_task_path_dispatches_ungated_tool():
    scripted = [
        (
            ["시간을 확인할게요. "],
            FakeMessage(
                [TextBlock("시간을 확인할게요. "), ToolUseBlock("t1", "get_time", {})],
                "tool_use",
            ),
        ),
        (["지금은 오후 3시입니다."],
         FakeMessage([TextBlock("지금은 오후 3시입니다.")], "end_turn")),
    ]
    client = FakeAnthropic(scripted)
    reg = ToolRegistry()
    reg.register(get_time)
    confirm_calls = []

    async def confirm(prompt):
        confirm_calls.append(prompt)
        return True

    brain = Brain(FakeSettings(), FakeMemory(), _PERSONA, client=client,
                  registry=reg, confirm=confirm)
    out = _collect(brain, "지금 몇 시야?")
    assert out[0] == TASK_FILLER
    assert "오후 3시" in "".join(out)
    assert confirm_calls == []  # get_time is not gated
    first = client.messages.calls[0]
    assert first["model"] == "claude-opus-4-8"
    assert first["thinking"] == {"type": "adaptive"}
    assert first["output_config"] == {"effort": "high"}
    assert first["tools"] == reg.tools()
    tool_result = client.messages.calls[1]["messages"][-1]["content"][0]
    assert tool_result["type"] == "tool_result"
    assert tool_result["tool_use_id"] == "t1"
    assert "시" in tool_result["content"]


def test_gated_tool_declined_blocks_execution():
    executed = {"v": False}

    @beta_async_tool
    async def delete_file(path: str) -> str:
        """파일을 영구 삭제합니다.

        Args:
            path: 삭제할 파일 경로.
        """
        executed["v"] = True
        return "삭제됨"

    scripted = [
        ([], FakeMessage([ToolUseBlock("d1", "delete_file", {"path": "/tmp/x"})], "tool_use")),
        (["요청을 취소했습니다."], FakeMessage([TextBlock("요청을 취소했습니다.")], "end_turn")),
    ]
    client = FakeAnthropic(scripted)
    reg = ToolRegistry()
    reg.register(delete_file, gated=True)
    prompts = []

    async def confirm(prompt):
        prompts.append(prompt)
        return False

    brain = Brain(FakeSettings(), FakeMemory(), _PERSONA, client=client,
                  registry=reg, confirm=confirm)
    out = _collect(brain, "파일 삭제 실행해줘")
    assert executed["v"] is False
    assert len(prompts) == 1 and "delete_file" in prompts[0]
    tool_result = client.messages.calls[1]["messages"][-1]["content"][0]
    assert tool_result["type"] == "tool_result" and "취소" in tool_result["content"]
    assert out[0] == TASK_FILLER
    assert "".join(out[1:]).endswith("취소했습니다.")


def test_gated_tool_approved_runs():
    executed = {"v": False}

    @beta_async_tool
    async def delete_file(path: str) -> str:
        """파일을 영구 삭제합니다.

        Args:
            path: 삭제할 파일 경로.
        """
        executed["v"] = True
        return "삭제 완료"

    scripted = [
        ([], FakeMessage([ToolUseBlock("d1", "delete_file", {"path": "/tmp/x"})], "tool_use")),
        (["삭제했습니다."], FakeMessage([TextBlock("삭제했습니다.")], "end_turn")),
    ]
    client = FakeAnthropic(scripted)
    reg = ToolRegistry()
    reg.register(delete_file, gated=True)

    async def confirm(prompt):
        return True

    brain = Brain(FakeSettings(), FakeMemory(), _PERSONA, client=client,
                  registry=reg, confirm=confirm)
    out = _collect(brain, "파일 삭제 실행해줘")
    assert executed["v"] is True
    tool_result = client.messages.calls[1]["messages"][-1]["content"][0]
    assert "삭제 완료" in tool_result["content"]
    assert out[0] == TASK_FILLER
    assert "".join(out[1:]) == "삭제했습니다."


def test_pause_turn_resends_without_tool_result():
    scripted = [
        (["검색 중..."], FakeMessage([TextBlock("검색 중...")], "pause_turn")),
        (["결과입니다."], FakeMessage([TextBlock("결과입니다.")], "end_turn")),
    ]
    client = FakeAnthropic(scripted)
    reg = ToolRegistry()
    reg.register({"type": "web_search_20260209", "name": "web_search"})

    async def confirm(prompt):
        return True

    brain = Brain(FakeSettings(), FakeMemory(), _PERSONA, client=client,
                  registry=reg, confirm=confirm)
    out = _collect(brain, "최신 뉴스 검색해줘")
    assert out[0] == TASK_FILLER
    assert "".join(out[1:]) == "검색 중...결과입니다."
    # Second call carries the assistant turn but NO tool_result user message.
    second = client.messages.calls[1]["messages"]
    assert second[-1]["role"] == "assistant"
