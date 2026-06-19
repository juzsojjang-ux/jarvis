import asyncio
from jarvis.brain import gating
from jarvis.core.control_gate import TRUST_GATE


class _Settings:
    bash_auto_allow = True


class _Brain:
    def __init__(self, confirm=None, remote=False):
        self._settings = _Settings()
        self._confirm = confirm
        self.remote_mode = remote


def _go(brain, name, inp):
    return asyncio.run(gating.gate_decision(brain, name, inp))


def test_read_and_local_auto_allow():
    b = _Brain(confirm=None)
    assert _go(b, "mcp__jarvis__get_time", {})[0] is True
    assert _go(b, "Bash", {"command": "ls"})[0] is True            # 느슨


def test_catastrophic_denied_even_with_confirm():
    async def yes(p): return True
    ok, why = _go(_Brain(confirm=yes), "Bash", {"command": "rm -rf /"})
    assert ok is False and "안전" in why


def test_send_requires_confirm():
    asked = []
    async def yes(p): asked.append(p); return True
    ok, _ = _go(_Brain(confirm=yes), "mcp__jarvis__send_mail", {"to": "a", "subject": "s"})
    assert ok is True and asked
    ok2, why2 = _go(_Brain(confirm=None), "mcp__jarvis__send_mail", {"to": "a"})
    assert ok2 is False


def test_remote_blocks_non_readonly():
    b = _Brain(confirm=None, remote=True)
    assert _go(b, "mcp__jarvis__get_time", {})[0] is True
    assert _go(b, "mcp__jarvis__open_app", {"app": "x"})[0] is False


def test_trust_gate_allows():
    TRUST_GATE.enable(5.0)
    try:
        assert _go(_Brain(confirm=None), "Write", {"file_path": "/etc/hosts"})[0] is True
    finally:
        TRUST_GATE.disable()


def test_build_hooks_denies_catastrophic():
    hooks = gating.build_hooks(_Brain())
    cb = hooks["PreToolUse"][0].hooks[0]
    out = asyncio.run(cb({"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}}, "t", {}))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    ok = asyncio.run(cb({"tool_name": "Read", "tool_input": {"file_path": "/tmp/x"}}, "t", {}))
    assert ok == {}


def test_send_denied_when_user_rejects():
    async def no(p): return False
    ok, why = _go(_Brain(confirm=no), "mcp__jarvis__send_mail", {"to": "a"})
    assert ok is False and "취소" in why


def test_remote_allows_safe_builtin():
    b = _Brain(confirm=None, remote=True)
    assert _go(b, "Read", {"file_path": "/tmp/x"})[0] is True
    assert _go(b, "Bash", {"command": "ls"})[0] is False   # 원격에선 Bash 차단


# ---------------------------------------------------------------------------
# Item 2: is_catastrophic runs BEFORE remote allowlist
# ---------------------------------------------------------------------------


def test_catastrophic_denied_before_remote_allowlist():
    b = _Brain(confirm=None, remote=True)
    ok, why = _go(b, "Read", {"file_path": "/Users/x/.ssh/id_rsa"})
    assert ok is False
    assert "안전" in why


# ---------------------------------------------------------------------------
# Item 5: plugin scan skipped when plugins disabled
# ---------------------------------------------------------------------------


class _SettingsNoPlugin:
    bash_auto_allow = True
    plugins_enabled = False


class _BrainNoPlugin:
    def __init__(self):
        self._settings = _SettingsNoPlugin()
        self._confirm = None
        self.remote_mode = False


def test_plugin_scan_skipped_external_mcp_still_denied():
    b = _BrainNoPlugin()
    ok, why = _go(b, "mcp__premiere__x", {})
    # EXTERNAL_MCP → confirm required → no confirm → deny (no plugin I/O needed)
    assert ok is False
