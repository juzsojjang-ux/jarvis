import asyncio
import types

from jarvis.brain.subscription import _GUIDANCE, SubscriptionBrain


class FakeText:
    def __init__(self, t): self.text = t


class FakeAssistant:
    def __init__(self, *texts): self.content = [FakeText(t) for t in texts]


class FakeStreamEvent:
    def __init__(self, text=None, type_="content_block_delta"):
        self.event = ({"type": type_, "delta": {"type": "text_delta", "text": text}}
                      if text is not None else {"type": type_})


class FakeToolStart(FakeStreamEvent):
    def __init__(self, kind="tool_use"):
        self.event = {"type": "content_block_start", "content_block": {"type": kind}}


class FakeOther:
    pass


class FakeOptions:
    def __init__(self, **kw): self.kw = kw


class FakeClient:
    instances = 0

    def __init__(self, options=None):
        FakeClient.instances += 1
        self.options = options
        self.connected = False
        self.queries = []
        self.script = []  # messages to emit per receive_response

    async def connect(self):
        self.connected = True

    async def query(self, prompt, session_id="default"):
        self.queries.append(prompt)

    async def receive_response(self):
        for m in self.script:
            yield m

    async def disconnect(self):
        self.connected = False


def _brain(settings=None):
    FakeClient.instances = 0
    return SubscriptionBrain(
        settings or types.SimpleNamespace(subscription_model=""),
        types.SimpleNamespace(text=lambda: "사용자 이름은 이성재."),
        "PERSONA가" * 10,
        client_cls=FakeClient,
        options_cls=FakeOptions,
        assistant_message=FakeAssistant,
        stream_event=FakeStreamEvent,
    )


async def _talk(brain, script, text="안녕"):
    client = await brain._ensure_client()
    client.script = script
    return [d async for d in brain.respond(text)], client


def test_streams_partial_deltas_and_skips_final_duplicate():
    async def run():
        b = _brain()
        out, client = await _talk(b, [
            FakeOther(),
            FakeStreamEvent("안녕"),
            FakeStreamEvent("하세요"),
            FakeAssistant("안녕하세요"),   # full text repeats — must NOT double-yield
        ])
        assert out == ["안녕", "하세요"]
        assert client.queries == ["안녕"]
    asyncio.run(run())


def test_tool_use_emits_filler_before_search_then_answer():
    async def run():
        b = _brain()
        out, _ = await _talk(b, [
            FakeToolStart("server_tool_use"),   # web search begins
            FakeStreamEvent("최근 결과는"),       # answer streams after
            FakeStreamEvent(" 이렇습니다."),
        ])
        assert out[0] == SubscriptionBrain.TOOL_FILLER  # immediate spoken ack
        assert "".join(out[1:]) == "최근 결과는 이렇습니다."
    asyncio.run(run())


def test_no_filler_when_no_tool_used():
    async def run():
        b = _brain()
        out, _ = await _talk(b, [FakeStreamEvent("안녕하세요")])
        assert SubscriptionBrain.TOOL_FILLER not in out
    asyncio.run(run())


def test_falls_back_to_assistant_message_without_partials():
    async def run():
        b = _brain()
        out, _ = await _talk(b, [FakeOther(), FakeAssistant("전체 답변")])
        assert out == ["전체 답변"]
    asyncio.run(run())


def test_client_is_persistent_across_turns():
    async def run():
        b = _brain()
        await _talk(b, [FakeAssistant("a")])
        await _talk(b, [FakeAssistant("b")])
        assert FakeClient.instances == 1  # no per-turn CLI cold start
    asyncio.run(run())


def test_options_isolated_streaming_and_key_stripped(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-leak")
    async def run():
        b = _brain()
        client = await b._ensure_client()
        kw = client.options.kw
        assert "WebSearch" in kw["allowed_tools"]
        assert "mcp__jarvis__open_app" in kw["allowed_tools"]
        assert "jarvis" in kw["mcp_servers"]
        assert "Bash" in kw["disallowed_tools"] and "Write" in kw["disallowed_tools"]
        assert kw["setting_sources"] == [] and kw["include_partial_messages"] is True
        assert "ANTHROPIC_API_KEY" not in kw["env"]
    asyncio.run(run())


def test_system_prompt_has_persona_memory_guidance():
    sp = _brain()._system_prompt()
    assert "PERSONA" in sp and "이성재" in sp and _GUIDANCE in sp


def test_warm_connects():
    async def run():
        b = _brain()
        await b.warm()
        assert b._client is not None and b._client.connected
        await b.close()
        assert b._client is None
    asyncio.run(run())


def test_subscription_model_passed_when_set():
    async def run():
        b = _brain(types.SimpleNamespace(subscription_model="claude-opus-4-8"))
        client = await b._ensure_client()
        assert client.options.kw["model"] == "claude-opus-4-8"
    asyncio.run(run())
