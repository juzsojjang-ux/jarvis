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


def test_nondestructive_bash_auto_allows_loose():
    brain = _brain(confirm=None)               # confirm 없어도
    assert _decide(brain, "Bash", {"command": "ls ~/Desktop"}).behavior == "allow"


def test_inscope_write_auto_allows_loose():
    import os
    brain = _brain(confirm=None)
    inside = os.path.join(os.path.expanduser("~"), "note.txt")
    assert _decide(brain, "Write", {"file_path": inside}).behavior == "allow"


def test_catastrophic_denied_even_with_confirm():
    async def yes(p): return True
    brain = _brain(confirm=yes)
    assert _decide(brain, "Bash", {"command": "rm -rf /"}).behavior == "deny"
    assert _decide(brain, "Read", {"file_path": "/Users/x/.ssh/id_rsa"}).behavior == "deny"


def test_destructive_tool_denied_on_no():
    async def confirm(prompt):
        return False

    brain = _brain(confirm=confirm)
    res = _decide(brain, "Write", {"file_path": "/Users/x/note.txt"})
    assert res.behavior == "deny"
    assert "취소" in res.message


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
    asyncio.run(brain._can_use_tool("Bash", {"command": "rm -rf x"}, _ctx()))
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
