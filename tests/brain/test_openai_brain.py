"""GPTBrain 테스트 — 가짜 client 주입, 실제 API 미호출."""
import asyncio
import json
import types as pyt

from jarvis.brain.openai_brain import GPTBrain
from jarvis.core.config import Settings


def _tc(id, name, args):
    return pyt.SimpleNamespace(
        id=id,
        function=pyt.SimpleNamespace(name=name, arguments=json.dumps(args)),
    )


def _msg(content=None, tool_calls=None):
    return pyt.SimpleNamespace(content=content, tool_calls=tool_calls)


def _resp(message):
    return pyt.SimpleNamespace(choices=[pyt.SimpleNamespace(message=message)])


class _FakeCompletions:
    def __init__(self, scripted):
        self.scripted = list(scripted)
        self.calls = []

    async def create(self, model=None, messages=None, tools=None, tool_choice=None):
        self.calls.append(messages)
        return self.scripted.pop(0)


class _FakeChat:
    def __init__(self, scripted):
        self.completions = _FakeCompletions(scripted)


class _FakeClient:
    def __init__(self, scripted):
        self.chat = _FakeChat(scripted)

    async def close(self):
        pass


def _brain(scripted, **kw):
    return GPTBrain(Settings(), kw.pop("memory", None), "p" * 4096, client=_FakeClient(scripted), **kw)


async def _collect(agen):
    return [x async for x in agen]


def test_plain_answer_splits_ko():
    b = _brain([_resp(_msg(content="Two o'clock, sir.[KO] 두 시입니다, 주인님."))])
    out = "".join(asyncio.run(_collect(b.respond("몇시야"))))
    assert out.strip() == "Two o'clock, sir." and b.last_subtitle == "두 시입니다, 주인님."


def test_tool_call_then_answer():
    scripted = [
        _resp(_msg(tool_calls=[_tc("c1", "get_time", {})])),
        _resp(_msg(content="It is time, sir.[KO] 시간입니다.")),
    ]
    b = _brain(scripted)
    out = "".join(asyncio.run(_collect(b.respond("몇시야"))))
    assert "time" in out.lower() and b.last_subtitle == "시간입니다."


def test_send_denied_without_confirm():
    scripted = [
        _resp(_msg(tool_calls=[_tc("c1", "send_message", {"recipient": "민지", "text": "hi"})])),
        _resp(_msg(content="Couldn't, sir.[KO] 못 보냈습니다.")),
    ]
    b = _brain(scripted)
    asyncio.run(_collect(b.respond("보내줘")))
    # 2nd call's messages should include a tool message with the refusal
    msgs = b._client().chat.completions.calls[1]
    toolmsgs = [m for m in msgs if m.get("role") == "tool"]
    assert toolmsgs and ("취소" in toolmsgs[0]["content"] or "확인" in toolmsgs[0]["content"])


def test_remote_blocks_action():
    scripted = [
        _resp(_msg(tool_calls=[_tc("c1", "open_app", {"app": "Notes"})])),
        _resp(_msg(content="Remote.[KO] 원격.")),
    ]
    b = _brain(scripted)
    b.remote_mode = True
    asyncio.run(_collect(b.respond("메모 열어")))
    msgs = b._client().chat.completions.calls[1]
    toolmsgs = [m for m in msgs if m.get("role") == "tool"]
    assert toolmsgs and "원격" in toolmsgs[0]["content"]


def test_translate():
    b = _brain([_resp(_msg(content="Hello"))])
    assert asyncio.run(b.translate("안녕", "English")) == "Hello"


def test_protocol_and_factory():
    from jarvis.brain.base import Brain
    assert isinstance(_brain([]), Brain)
    import types as t
    from jarvis.brain.factory import make_brain
    from jarvis.brain.openai_brain import GPTBrain
    s = t.SimpleNamespace(
        brain_provider="gpt",
        brain_backend="subscription",
        subscription_model="",
        gpt_model="gpt-4o",
    )
    assert isinstance(make_brain(s, None, "p" * 4096), GPTBrain)


def test_memory_text_in_system_prompt():
    class _Mem:
        def text(self): return "주인님은 매운 음식을 못 드신다."
    b = _brain([], memory=_Mem())
    sp = b._system_prompt()
    assert "매운 음식" in sp and "# 기억" in sp


def test_history_injected_and_saved(monkeypatch, tmp_path):
    monkeypatch.setattr("jarvis.brain.history.DEFAULT_HISTORY_PATH", tmp_path / "h.jsonl")

    # Turn 1: brain responds with a canned answer, history should be saved.
    b = _brain([_resp(_msg(content="First answer.[KO] 첫 번째 답변."))])
    asyncio.run(_collect(b.respond("첫 번째 질문")))
    assert len(b._history.turns) == 1
    assert b._history.turns[0] == ("첫 번째 질문", "First answer.")

    # Turn 2: a NEW brain instance loads history from disk; its outgoing user message must
    # contain the context marker, confirming history was injected.
    b2 = _brain([_resp(_msg(content="Second answer.[KO] 두 번째 답변."))])
    asyncio.run(_collect(b2.respond("두 번째 질문")))
    # The first call's messages[1] is the user message — check its content.
    first_call_messages = b2._client().chat.completions.calls[0]
    user_content = next(m["content"] for m in first_call_messages if m["role"] == "user")
    assert "이전 대화 맥락" in user_content
