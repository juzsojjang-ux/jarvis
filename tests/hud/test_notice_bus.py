"""HUD 정보 패널 전역 싱크(notice_bus) + show_panel/hide_panel 도구 테스트."""
from __future__ import annotations

import asyncio

import pytest

from jarvis.hud import notice_bus
from jarvis.tools.registry import neutral_tools


@pytest.fixture(autouse=True)
def _reset_sink():
    yield
    notice_bus.set_sink(None)  # 전역 싱크가 테스트 간 새지 않게


def test_sink_receives_show_and_hide():
    got = []
    notice_bus.set_sink(got.append)
    assert notice_bus.show("hi") is True
    assert got == ["hi"]
    assert notice_bus.hide() is True
    assert got[-1] == ""


def test_no_sink_returns_false():
    notice_bus.set_sink(None)
    assert notice_bus.show("x") is False


def test_sink_exception_is_safe():
    def boom(_):
        raise RuntimeError("nope")

    notice_bus.set_sink(boom)
    assert notice_bus.show("y") is False  # 도구가 깨지지 않음


def test_show_panel_tool_publishes_content():
    got = []
    notice_bus.set_sink(got.append)
    tools = {t.name: t for t in neutral_tools()}
    out = asyncio.run(tools["show_panel"].call({"content": "오늘 일정 3건"}))
    assert got == ["오늘 일정 3건"]
    assert "표시" in out


def test_hide_panel_tool_clears():
    got = []
    notice_bus.set_sink(got.append)
    tools = {t.name: t for t in neutral_tools()}
    asyncio.run(tools["hide_panel"].call({}))
    assert got[-1] == ""


def test_show_panel_empty_content_asks():
    got = []
    notice_bus.set_sink(got.append)
    tools = {t.name: t for t in neutral_tools()}
    out = asyncio.run(tools["show_panel"].call({"content": "   "}))
    assert got == []  # 빈 내용은 패널에 안 띄움
    assert "보여" in out
