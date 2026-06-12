"""윈도우 부팅 회귀 — SIGHUP 부재, frozen 자식 디스패치(포크폭탄), 단일 인스턴스.

전부 2026-06-12 윈도우 배포에서 실제로 터진 크래시들의 고정 테스트다:
  - AttributeError: module 'signal' has no attribute 'SIGHUP'
  - frozen 번들에서 overlay/tray 스폰이 본체를 재귀 부팅(1→2→4… 증식)
"""
from __future__ import annotations

import signal
import subprocess
import sys
from pathlib import Path

from jarvis.__main__ import _acquire_singleton, _child_cmd, _install_exit_signals

REPO = Path(__file__).resolve().parents[1]


class _FakeLoop:
    def __init__(self, raise_ni=False):
        self.raise_ni = raise_ni
        self.registered = []

    def add_signal_handler(self, sig, cb):
        if self.raise_ni:  # Windows Proactor 루프 동작
            raise NotImplementedError
        self.registered.append(sig)


class _FakeTask:
    def cancel(self):
        pass


def test_signals_skip_missing_sighup(monkeypatch):
    """SIGHUP이 없는 플랫폼(Windows)에서 AttributeError 없이 SIGTERM만 등록."""
    monkeypatch.delattr(signal, "SIGHUP", raising=False)
    loop = _FakeLoop()
    _install_exit_signals(loop, _FakeTask())  # 크래시하면 테스트 실패
    assert loop.registered == [signal.SIGTERM]


def test_signals_tolerate_not_implemented():
    """Windows 이벤트 루프(add_signal_handler 미지원)에서도 조용히 통과."""
    _install_exit_signals(_FakeLoop(raise_ni=True), _FakeTask())


def test_child_cmd_dev_uses_module_flag():
    assert _child_cmd("jarvis.hud.tray", "123") == [
        sys.executable, "-m", "jarvis.hud.tray", "123"]


def test_child_cmd_frozen_uses_child_flag(monkeypatch):
    """frozen 번들에서는 -m 대신 --child= — 본체 재귀 부팅(포크폭탄) 방지."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert _child_cmd("jarvis.hud.overlay_win", "http://u") == [
        sys.executable, "--child=jarvis.hud.overlay_win", "http://u"]


def test_singleton_blocks_second_instance(monkeypatch):
    import socket
    free = socket.socket()
    free.bind(("127.0.0.1", 0))
    port = free.getsockname()[1]
    free.close()
    monkeypatch.setenv("JARVIS_SINGLETON_PORT", str(port))
    first = _acquire_singleton()
    assert first is not None
    assert _acquire_singleton() is None  # 두 번째 부팅은 거부
    first.close()


def test_singleton_disabled_with_port_zero(monkeypatch):
    monkeypatch.setenv("JARVIS_SINGLETON_PORT", "0")
    assert _acquire_singleton() is not None


def test_launcher_rejects_unknown_child():
    """디스패치가 본체 부팅보다 먼저 도는지 — 미허용 모듈은 즉시 exit 2
    (무거운 임포트 전에 끝나므로 1초 안에 끝난다)."""
    res = subprocess.run(
        [sys.executable, str(REPO / "packaging" / "jarvis_launch.py"),
         "--child=evil.module"],
        capture_output=True, timeout=15)
    assert res.returncode == 2
