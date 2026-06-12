"""보조 두뇌 자문 — 프로바이더 별칭, 실패 시 한국어 안내(절대 raise 금지), 타임아웃."""
from __future__ import annotations

import asyncio

import pytest

from jarvis.brain import consult as mod


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def test_unknown_provider_is_friendly():
    out = run(mod.consult("llama", "q", settings=object()))
    assert "모르는 보조 두뇌" in out


def test_claude_redirects_to_main():
    out = run(mod.consult("클로드", "q", settings=object()))
    assert "메인 두뇌" in out


def test_empty_question():
    out = run(mod.consult("gemini", "  ", settings=object()))
    assert "비어" in out


def test_korean_aliases_route(monkeypatch):
    seen = {}
    async def fake(question, settings):
        seen["q"] = question
        return "답"
    out = run(mod.consult("제미나이", "질문", settings=object(), _impl=fake))
    assert out == "답" and seen["q"] == "질문"


def test_impl_exception_becomes_korean_message():
    async def boom(question, settings):
        raise RuntimeError("kaput")
    out = run(mod.consult("gpt", "q", settings=object(), _impl=boom))
    assert "자문 실패" in out and "kaput" in out


def test_timeout_message():
    async def slow(question, settings):
        await asyncio.sleep(5)
    out = run(mod.consult("gemini", "q", settings=object(), _impl=slow, timeout_s=0.05))
    assert "답하지 않았습니다" in out


def test_gemini_without_key_explains(monkeypatch):
    monkeypatch.setattr("jarvis.brain.gemini._gemini_key", lambda s: None)
    out = run(mod._consult_gemini("q", object()))
    assert "API 키" in out


def test_available_reports_bool(monkeypatch):
    monkeypatch.setattr("jarvis.brain.gemini._gemini_key", lambda s: "k")
    monkeypatch.setattr("jarvis.brain.codex_auth.is_codex_logged_in", lambda: False)
    avail = mod.available()
    assert avail == {"gemini": True, "gpt": False}


def test_gemini_with_fake_client():
    class Part:
        text = "제미나이 답변"
    class Content:
        parts = [Part()]
    class Cand:
        content = Content()
    class Resp:
        candidates = [Cand()]
    class Models:
        async def generate_content(self, **kw):
            return Resp()
    class Aio:
        models = Models()
    class Client:
        aio = Aio()
    out = run(mod._consult_gemini("q", object(), client=Client()))
    assert out == "제미나이 답변"


@pytest.mark.parametrize("alias,target", [("지피티", "gpt"), ("chatgpt", "gpt"),
                                          ("google", "gemini")])
def test_alias_table(alias, target, monkeypatch):
    captured = {}
    async def fake(question, settings):
        captured["ok"] = True
        return target
    out = run(mod.consult(alias, "q", settings=object(), _impl=fake))
    assert out == target
