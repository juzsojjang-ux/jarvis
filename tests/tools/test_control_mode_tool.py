"""screen_control_mode 도구 — 두뇌가 어떤 표현이든 게이트를 켤 수 있게."""
from __future__ import annotations

import asyncio

from jarvis.core.control_gate import CONTROL_GATE
from jarvis.tools.registry import neutral_tools


def test_screen_control_mode_tool_toggles_gate():
    tools = {t.name: t for t in neutral_tools()}
    CONTROL_GATE.disable()
    out = asyncio.run(tools["screen_control_mode"].call({"state": "on"}))
    assert CONTROL_GATE.is_on() and "켰" in out
    out = asyncio.run(tools["screen_control_mode"].call({"state": "off"}))
    assert not CONTROL_GATE.is_on() and "껐" in out


def test_screen_control_mode_bad_state():
    tools = {t.name: t for t in neutral_tools()}
    out = asyncio.run(tools["screen_control_mode"].call({"state": "maybe"}))
    assert "on" in out
