import asyncio
import types

from jarvis.brain.subscription import _GUIDANCE, SubscriptionBrain


class FakeText:
    def __init__(self, t): self.text = t


class FakeAssistant:
    def __init__(self, *texts): self.content = [FakeText(t) for t in texts]


class FakeOther:  # SystemMessage / RateLimitEvent / ResultMessage analogue
    pass


class FakeOptions:
    def __init__(self, **kw): self.kw = kw


def _make_query(messages, captured):
    async def fake_query(*, prompt, options):
        captured["prompt"] = prompt
        captured["options"] = options
        for m in messages:
            yield m
    return fake_query


def _brain(messages, captured, settings=None):
    return SubscriptionBrain(
        settings or types.SimpleNamespace(subscription_model=""),
        types.SimpleNamespace(text=lambda: "사용자 이름은 이성재."),
        "PERSONA가" * 10,
        query=_make_query(messages, captured),
        options_cls=FakeOptions,
        assistant_message=FakeAssistant,
    )


async def _collect(brain, text="안녕"):
    return [d async for d in brain.respond(text)]


def test_respond_yields_only_assistant_text():
    captured = {}
    msgs = [FakeOther(), FakeAssistant("안녕하세요 ", "성재님."), FakeOther()]
    out = asyncio.run(_collect(_brain(msgs, captured)))
    assert out == ["안녕하세요 ", "성재님."]
    assert captured["prompt"] == "안녕"


def test_options_strip_api_key_and_are_isolated(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-leak")
    captured = {}
    asyncio.run(_collect(_brain([FakeAssistant("x")], captured)))
    opts = captured["options"].kw
    assert opts["allowed_tools"] == [] and opts["setting_sources"] == []
    assert opts["max_turns"] == 1
    assert "ANTHROPIC_API_KEY" not in opts["env"]  # never bills the paid API


def test_system_prompt_has_persona_memory_guidance():
    sp = _brain([], {})._system_prompt()
    assert "PERSONA" in sp and "이성재" in sp and _GUIDANCE in sp


def test_subscription_model_passed_when_set():
    captured = {}
    settings = types.SimpleNamespace(subscription_model="claude-opus-4-8")
    asyncio.run(_collect(_brain([FakeAssistant("x")], captured, settings)))
    assert captured["options"].kw["model"] == "claude-opus-4-8"


def test_model_omitted_when_blank():
    captured = {}
    asyncio.run(_collect(_brain([FakeAssistant("x")], captured)))
    assert "model" not in captured["options"].kw


def test_warm_ok_with_injected_sdk():
    asyncio.run(_brain([], {}).warm())  # must not raise
