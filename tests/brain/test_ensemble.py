"""앙상블 — 병렬 자문 수집·실패 격리·컨텍스트 포맷·모드 결정."""
from __future__ import annotations

import asyncio

from jarvis.brain import ensemble as mod


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def _avail_both(monkeypatch):
    monkeypatch.setattr(mod, "available", lambda: {"gemini": True, "gpt": True})


def test_gathers_from_all_available(monkeypatch):
    _avail_both(monkeypatch)
    async def g(q, s): return "제미나이 의견"
    async def p(q, s): return "GPT 의견"
    out = run(mod.gather_opinions("q", settings=object(),
                                  _impls={"gemini": g, "gpt": p}))
    assert ("제미나이", "제미나이 의견") in out and ("GPT", "GPT 의견") in out


def test_failure_of_one_does_not_break(monkeypatch):
    _avail_both(monkeypatch)
    async def g(q, s): raise RuntimeError("down")
    async def p(q, s): return "GPT 의견"
    out = run(mod.gather_opinions("q", settings=object(),
                                  _impls={"gemini": g, "gpt": p}))
    assert out == [("GPT", "GPT 의견")]


def test_unavailable_skipped(monkeypatch):
    monkeypatch.setattr(mod, "available", lambda: {"gemini": False, "gpt": False})
    called = {}
    async def g(q, s):
        called["x"] = True
        return "x"
    out = run(mod.gather_opinions("q", settings=object(), _impls={"gemini": g}))
    assert out == [] and not called


def test_unavailable_notice_text_excluded(monkeypatch):
    _avail_both(monkeypatch)
    async def g(q, s): return "제미나이 자문 불가 — API 키가 없습니다."
    async def p(q, s): return "정상 의견"
    out = run(mod.gather_opinions("q", settings=object(),
                                  _impls={"gemini": g, "gpt": p}))
    assert out == [("GPT", "정상 의견")]


def test_empty_question_short_circuits():
    out = run(mod.gather_opinions("  ", settings=object(), _impls={}))
    assert out == []


def test_format_context_includes_labels_and_guidance():
    ctx = mod.format_context([("제미나이", "A"), ("GPT", "B")])
    assert "(제미나이) A" in ctx and "(GPT) B" in ctx and "종합" in ctx
    assert ctx.endswith("\n\n")


def test_format_context_empty():
    assert mod.format_context([]) == ""


def test_mode_default_and_env(monkeypatch):
    monkeypatch.delenv("JARVIS_ENSEMBLE_MODE", raising=False)
    assert mod.mode(object()) == "deep"
    monkeypatch.setenv("JARVIS_ENSEMBLE_MODE", "always")
    assert mod.mode(object()) == "always"
    monkeypatch.setenv("JARVIS_ENSEMBLE_MODE", "괴상한값")
    assert mod.mode(object()) == "deep"
