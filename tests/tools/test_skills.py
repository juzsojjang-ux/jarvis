"""사용자 스킬 자동 로더 테스트(자가 기능 확장)."""
from __future__ import annotations

import asyncio

from jarvis.tools.skills import load_skill_tools

_COIN = (
    'async def handler(args):\n'
    '    return "앞면"\n'
    'TOOLS = [{"name": "coin_flip", "description": "동전",\n'
    '          "parameters": {"type": "object", "properties": {}}, "handler": handler}]\n'
)


def test_loads_skill_from_dir(tmp_path):
    (tmp_path / "coin.py").write_text(_COIN, encoding="utf-8")
    tools = load_skill_tools(tmp_path)
    assert len(tools) == 1 and tools[0].name == "coin_flip"


def test_skill_handler_wrapped_and_callable(tmp_path):
    (tmp_path / "x.py").write_text(
        'def handler(args):\n    return "ok:" + str(args.get("v"))\n'
        'TOOLS = [{"name": "x", "description": "d", "parameters": {}, "handler": handler}]\n',
        encoding="utf-8")
    tools = load_skill_tools(tmp_path)
    out = asyncio.run(tools[0].call({"v": 3}))
    assert out == "ok:3"


def test_broken_skill_skipped_others_load(tmp_path):
    (tmp_path / "bad.py").write_text("this is not python !!!\n", encoding="utf-8")
    (tmp_path / "good.py").write_text(
        'async def h(a):\n    return "y"\n'
        'TOOLS = [{"name": "g", "description": "d", "parameters": {}, "handler": h}]\n',
        encoding="utf-8")
    tools = load_skill_tools(tmp_path)
    assert [t.name for t in tools] == ["g"]


def test_underscore_files_ignored(tmp_path):
    (tmp_path / "_helper.py").write_text("X = 1\n", encoding="utf-8")
    assert load_skill_tools(tmp_path) == []


def test_missing_dir_returns_empty(tmp_path):
    assert load_skill_tools(tmp_path / "nope") == []


def test_skills_flow_into_sdk_tools_for_claude_brain(monkeypatch, tmp_path):
    # 자가 코딩 시연에서 발견된 구멍: 스킬이 클로드(구독) 두뇌의 MCP 도구에
    # 합류하지 않으면 클로드만 새 능력을 못 쓴다 — build_tool_objects에 포함 보장.
    (tmp_path / "echo.py").write_text(
        'async def h(a):\n    return "메아리: " + str(a.get("msg"))\n'
        'TOOLS = [{"name": "echo_skill", "description": "메아리",\n'
        '          "parameters": {"type": "object", "properties": {"msg": {"type": "string"}}},\n'
        '          "handler": h}]\n', encoding="utf-8")
    monkeypatch.setattr("jarvis.tools.skills.DEFAULT_SKILLS_DIR", tmp_path)
    from jarvis.tools.jarvis_mcp import build_tool_objects
    names = [t.name for t in build_tool_objects(None)]
    assert "echo_skill" in names          # 클로드 두뇌 경로에 스킬 포함
    # neutral_tools(gemini/gpt)에도 같은 경로로 정확히 1번만 들어간다(중복 금지)
    from jarvis.tools.registry import neutral_tools
    nnames = [t.name for t in neutral_tools(None)]
    assert nnames.count("echo_skill") == 1


def test_skill_callable_through_sdk_wrapper(monkeypatch, tmp_path):
    import asyncio
    (tmp_path / "add.py").write_text(
        'def h(a):\n    return str(int(a.get("x",0)) + int(a.get("y",0)))\n'
        'TOOLS = [{"name": "add_skill", "description": "더하기", "parameters": {},\n'
        '          "handler": h}]\n', encoding="utf-8")
    monkeypatch.setattr("jarvis.tools.skills.DEFAULT_SKILLS_DIR", tmp_path)
    from jarvis.tools.registry import neutral_tools
    t = {x.name: x for x in neutral_tools(None)}["add_skill"]
    assert asyncio.run(t.call({"x": 2, "y": 40})) == "42"
