"""바탕화면 바로가기 생성 + 셋업 UI 연동 테스트(실제 frozen/OS 없이 주입으로)."""
from __future__ import annotations

import json
import urllib.request

from jarvis.setup.server import SetupServer
from jarvis.setup.shortcut import create_desktop_shortcut


# --- create_desktop_shortcut ------------------------------------------------
def test_dev_mode_skips_when_no_target(tmp_path):
    desk = tmp_path / "Desktop"
    desk.mkdir()
    ok, msg = create_desktop_shortcut(target=None, desktop=str(desk), system="darwin")
    assert not ok and "개발" in msg


def test_mac_creates_symlink(tmp_path):
    target = tmp_path / "Applications" / "JARVIS.app"
    target.mkdir(parents=True)
    desk = tmp_path / "Desktop"
    desk.mkdir()
    ok, msg = create_desktop_shortcut(target=str(target), desktop=str(desk), system="darwin")
    assert ok
    link = desk / "JARVIS.app"
    assert link.is_symlink() and link.resolve() == target.resolve()


def test_mac_already_on_desktop_is_noop(tmp_path):
    desk = tmp_path / "Desktop"
    desk.mkdir()
    target = desk / "JARVIS.app"
    target.mkdir()
    ok, msg = create_desktop_shortcut(target=str(target), desktop=str(desk), system="darwin")
    assert ok and "이미" in msg


def test_mac_idempotent(tmp_path):
    target = tmp_path / "a" / "JARVIS.app"
    target.mkdir(parents=True)
    desk = tmp_path / "Desktop"
    desk.mkdir()
    create_desktop_shortcut(target=str(target), desktop=str(desk), system="darwin")
    ok, msg = create_desktop_shortcut(target=str(target), desktop=str(desk), system="darwin")
    assert ok and "이미" in msg


def test_windows_builds_lnk_command(tmp_path):
    calls = []

    def runner(cmd, **kw):
        calls.append(cmd)

    target = tmp_path / "JARVIS.exe"
    target.write_text("x")
    desk = tmp_path / "Desktop"
    desk.mkdir()
    ok, msg = create_desktop_shortcut(target=str(target), desktop=str(desk),
                                      system="win32", runner=runner)
    assert ok
    assert calls and calls[0][0] == "powershell"
    joined = " ".join(calls[0])
    assert "CreateShortcut" in joined and "JARVIS.lnk" in joined and str(target) in joined


def test_unsupported_os(tmp_path):
    desk = tmp_path / "Desktop"
    desk.mkdir()
    ok, _ = create_desktop_shortcut(target=str(tmp_path / "x"), desktop=str(desk), system="linux")
    assert not ok


# --- 셋업 UI 연동(POST /setup desktop_shortcut) ------------------------------
async def _ok(provider, key):
    return True, "ok"


def _noop_store(provider, key):
    pass


def _post(port, body):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/setup",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def test_setup_creates_shortcut_when_checked():
    calls = []

    def _shortcut():
        calls.append(1)
        return (True, "바탕화면에 아이콘을 만들었습니다.")

    srv = SetupServer(validator=_ok, store_save=_noop_store, shortcut_fn=_shortcut)
    srv.start()
    try:
        _, data = _post(srv.port, {"provider": "claude", "key": "", "desktop_shortcut": True})
        assert data["ok"] and calls == [1]
        assert "아이콘" in data["message"]
    finally:
        srv.stop()


def test_setup_skips_shortcut_when_unchecked():
    calls = []
    srv = SetupServer(validator=_ok, store_save=_noop_store,
                      shortcut_fn=lambda: (calls.append(1) or (True, "x")))
    srv.start()
    try:
        _, data = _post(srv.port, {"provider": "claude", "key": "", "desktop_shortcut": False})
        assert data["ok"] and calls == []
    finally:
        srv.stop()
