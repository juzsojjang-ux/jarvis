import asyncio

from jarvis.brain.subscription import SubscriptionBrain
from jarvis.core.config import Settings


def _brain(confirm=None):
    return SubscriptionBrain(Settings(), None, "p" * 4096, confirm=confirm)


def _ctx():
    from claude_agent_sdk import ToolPermissionContext
    return ToolPermissionContext(tool_use_id="t1")


def _decide(brain, tool, inp):
    return asyncio.run(brain._can_use_tool(tool, inp, _ctx()))


def test_readonly_tools_auto_allowed():
    brain = _brain(confirm=None)
    for tool in ("Read", "Glob", "Grep", "TodoWrite", "WebSearch", "WebFetch"):
        assert _decide(brain, tool, {}).behavior == "allow"


def test_destructive_tool_denied_without_confirm():
    brain = _brain(confirm=None)
    assert _decide(brain, "Bash", {"command": "rm -rf x"}).behavior == "deny"
    assert _decide(brain, "Write", {"file_path": "/x"}).behavior == "deny"


def test_destructive_tool_allowed_on_yes():
    asked = []

    async def confirm(prompt):
        asked.append(prompt)
        return True

    brain = _brain(confirm=confirm)
    res = _decide(brain, "Bash", {"command": "ls ~/Desktop"})
    assert res.behavior == "allow"
    assert "ls ~/Desktop" in asked[0]


def test_destructive_tool_denied_on_no():
    async def confirm(prompt):
        return False

    brain = _brain(confirm=confirm)
    res = _decide(brain, "Write", {"file_path": "/Users/x/note.txt"})
    assert res.behavior == "deny"
    assert "note.txt" in res.message or "취소" in res.message


def test_jarvis_mcp_tools_auto_allowed():
    brain = _brain(confirm=None)
    assert _decide(brain, "mcp__jarvis__set_volume", {"level": 50}).behavior == "allow"


def test_factory_injects_confirm():
    from jarvis.brain.factory import make_brain
    calls = []

    async def confirm(prompt):
        calls.append(prompt)
        return True

    brain = make_brain(Settings(), None, "p" * 4096, confirm=confirm)
    asyncio.run(brain._can_use_tool("Bash", {"command": "echo hi"}, _ctx()))
    assert calls


def test_foreign_mcp_tool_not_bypassed_by_base_name():
    # mcp__타사__Read 처럼 끝 segment가 읽기셋과 같아도 자동 허용되면 안 된다.
    brain = _brain(confirm=None)
    assert _decide(brain, "mcp__evil__Read", {}).behavior == "deny"
    assert _decide(brain, "mcp__other__WebFetch", {}).behavior == "deny"
    # 진짜 jarvis 도구는 여전히 허용
    assert _decide(brain, "mcp__jarvis__get_time", {}).behavior == "allow"
    # 내장 Read는 여전히 허용
    assert _decide(brain, "Read", {}).behavior == "allow"
