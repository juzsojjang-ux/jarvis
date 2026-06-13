"""첫 설정 로그인 흐름 — 상태 파싱, OAuth 시작, 미설치/미로그인 안내."""
from __future__ import annotations

from jarvis.setup import login


class _R:
    def __init__(self, out=""):
        self.stdout = out


def test_claude_logged_in_parses_json():
    r = lambda cmd, **k: _R('noise\n{\n  "loggedIn": true,\n  "email": "x"\n}\ntail')
    assert login.claude_logged_in(r) is True


def test_claude_logged_out():
    assert login.claude_logged_in(lambda cmd, **k: _R('{"loggedIn": false}')) is False


def test_claude_status_failure_is_false():
    def boom(cmd, **k):
        raise FileNotFoundError("claude")
    assert login.claude_logged_in(boom) is False


def test_gpt_logged_in_uses_checker():
    assert login.gpt_logged_in(lambda: True) is True
    assert login.gpt_logged_in(lambda: False) is False


def test_login_status_dispatch():
    assert login.login_status("claude", runner=lambda cmd, **k: _R('{"loggedIn": true}'))
    assert login.login_status("gpt", checker=lambda: True)
    assert login.login_status("gemini") is False     # 키 방식 — 로그인 없음


def test_start_login_claude_missing_cli():
    ok, msg = login.start_login("claude", which=lambda c: None)
    assert not ok and "claude" in msg


def test_start_login_claude_spawns_browser(monkeypatch):
    monkeypatch.setattr(login, "claude_logged_in", lambda *a, **k: False)
    spawned = []
    ok, msg = login.start_login(
        "claude", spawn=lambda *a, **k: spawned.append(a[0]),
        which=lambda c: "/bin/claude")
    assert ok and spawned and spawned[0][:3] == ["claude", "auth", "login"]


def test_start_login_claude_already_logged_in(monkeypatch):
    monkeypatch.setattr(login, "claude_logged_in", lambda *a, **k: True)
    ok, msg = login.start_login("claude", which=lambda c: "/bin/claude")
    assert ok and "이미" in msg


def test_start_login_gpt_missing_codex(monkeypatch):
    monkeypatch.setattr(login, "gpt_logged_in", lambda *a, **k: False)
    ok, msg = login.start_login("gpt", which=lambda c: None)
    assert not ok and "codex" in msg


def test_start_login_unknown_provider():
    ok, msg = login.start_login("llama")
    assert not ok and "키 입력" in msg
