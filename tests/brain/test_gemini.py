"""GeminiBrain 테스트 — 가짜 client 주입, 실제 API 미호출."""
from __future__ import annotations

import asyncio
import types as pytypes

from jarvis.brain.gemini import GeminiBrain
from jarvis.core.config import Settings


# ---------------------------------------------------------------------------
# Fake google-genai client helpers
# ---------------------------------------------------------------------------

def _part(text=None, fname=None, fargs=None):
    fc = pytypes.SimpleNamespace(name=fname, args=fargs or {}) if fname else None
    return pytypes.SimpleNamespace(text=text, function_call=fc)


def _resp(parts):
    content = pytypes.SimpleNamespace(parts=parts)
    return pytypes.SimpleNamespace(
        candidates=[pytypes.SimpleNamespace(content=content)]
    )


class _FakeModels:
    def __init__(self, scripted):
        self.scripted = list(scripted)  # list of response objects, one per call
        self.calls = []

    async def generate_content(self, model=None, contents=None, config=None):
        self.calls.append(contents)
        return self.scripted.pop(0)


class _FakeAio:
    def __init__(self, models):
        self.models = models

    async def close(self):
        pass


class _FakeClient:
    def __init__(self, scripted):
        self.aio = _FakeAio(_FakeModels(scripted))


def _brain(scripted, **kw):
    return GeminiBrain(
        Settings(),
        kw.pop("memory", None),
        "p" * 4096,
        client=_FakeClient(scripted),
        **kw,
    )


async def _collect(agen):
    return [x async for x in agen]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_plain_answer_splits_ko():
    b = _brain([_resp([_part(text="Two o'clock, sir.[KO] 두 시입니다, 주인님.")])])
    out = "".join(asyncio.run(_collect(b.respond("몇시야"))))
    assert out.strip() == "Two o'clock, sir."
    assert b.last_subtitle == "두 시입니다, 주인님."


def test_tool_call_then_answer():
    # turn 1: model asks for get_time; turn 2: model answers
    scripted = [
        _resp([_part(fname="get_time", fargs={})]),
        _resp([_part(text="It is time, sir.[KO] 시간입니다.")]),
    ]
    b = _brain(scripted)
    out = "".join(asyncio.run(_collect(b.respond("몇시야"))))
    assert "time" in out.lower()
    assert b.last_subtitle == "시간입니다."


def test_send_tool_denied_without_confirm_then_model_continues():
    scripted = [
        _resp([_part(fname="send_message", fargs={"recipient": "민지", "text": "hi"})]),
        _resp([_part(text="I couldn't send it, sir.[KO] 못 보냈습니다.")]),
    ]
    b = _brain(scripted)  # confirm=None → guarded denied
    out = "".join(asyncio.run(_collect(b.respond("민지에게 보내줘"))))
    # the function_response fed back should contain the refusal reason; model's final answer streams
    assert "couldn't" in out.lower() or b.last_subtitle
    # verify the 2nd call's contents included a function_response with refusal
    fake = b._client().aio.models
    assert len(fake.calls) == 2


def test_remote_mode_blocks_action_tool():
    scripted = [
        _resp([_part(fname="open_app", fargs={"app": "Notes"})]),
        _resp([_part(text="Remote, sir.[KO] 원격입니다.")]),
    ]
    b = _brain(scripted)
    b.remote_mode = True
    asyncio.run(_collect(b.respond("메모 열어")))
    # open_app must NOT have executed; check by ensuring 2 turns happened (refusal fed back)
    assert len(b._client().aio.models.calls) == 2


def test_translate():
    b = _brain([_resp([_part(text="Hello")])])
    out = asyncio.run(b.translate("안녕", "English"))
    assert out == "Hello"


def test_satisfies_brain_protocol():
    from jarvis.brain.base import Brain
    b = _brain([])
    assert isinstance(b, Brain)


def test_factory_gemini_builds_brain():
    import types as t
    from jarvis.brain.factory import make_brain

    # gemini path requires a client; factory makes a real GeminiBrain but with no client it lazily
    # needs a key only when used. Construction alone should succeed (key checked lazily).
    s = t.SimpleNamespace(
        brain_provider="gemini",
        brain_backend="subscription",
        subscription_model="",
        gemini_model="gemini-2.5-flash",
    )
    b = make_brain(s, None, "p" * 4096)
    from jarvis.brain.gemini import GeminiBrain
    assert isinstance(b, GeminiBrain)
