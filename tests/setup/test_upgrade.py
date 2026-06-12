"""풀음성 업그레이드 엔드포인트(SetupServer) 테스트.

실제 torch 설치는 하지 않는다 — upgrade_cmd를 가짜 커맨드로 주입해서 실행/로그/
실패/동시성/모드검증만 검증한다.
"""
from __future__ import annotations

import sys
import time

from jarvis.setup.server import SetupServer, _default_upgrade_cmd


def _wait(srv: SetupServer, timeout: float = 5.0) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        s = srv.upgrade_status()
        if s["state"] in ("done", "error"):
            return s
        time.sleep(0.03)
    return srv.upgrade_status()


def test_upgrade_success_captures_log():
    srv = SetupServer(upgrade_cmd=lambda mode: [sys.executable, "-c", "print('UPGRADE_OK')"])
    ok, _ = srv._start_upgrade("pocket")
    assert ok
    s = _wait(srv)
    assert s["state"] == "done"
    assert "UPGRADE_OK" in s["log"]


def test_upgrade_failure_sets_error():
    srv = SetupServer(upgrade_cmd=lambda mode: [sys.executable, "-c", "import sys; sys.exit(3)"])
    ok, _ = srv._start_upgrade("rvc")
    assert ok
    s = _wait(srv)
    assert s["state"] == "error"
    assert "3" in s["log"]


def test_upgrade_rejects_bad_mode():
    srv = SetupServer()
    ok, msg = srv._start_upgrade("bogus")
    assert not ok
    assert "모드" in msg
    assert srv.upgrade_status()["state"] == "idle"


def test_upgrade_rejects_concurrent():
    slow = [sys.executable, "-c", "import time; time.sleep(1.5)"]
    srv = SetupServer(upgrade_cmd=lambda mode: slow)
    ok, _ = srv._start_upgrade("pocket")
    assert ok
    ok2, msg = srv._start_upgrade("pocket")
    assert not ok2
    assert "진행 중" in msg


def test_default_upgrade_cmd_shape():
    cmd = _default_upgrade_cmd("pocket")
    joined = " ".join(cmd)
    assert "upgrade_full_voice" in joined
    assert "pocket" in cmd
    # 플랫폼별 런처
    if sys.platform.startswith("win"):
        assert cmd[0] == "powershell"
    else:
        assert cmd[0] == "bash"
