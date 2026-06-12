"""부모 감시(procwatch) — 메인이 죽으면 오버레이/트레이가 따라 죽는 안전망 테스트."""
from __future__ import annotations

import os
import threading
import time

from jarvis.hud.procwatch import pid_alive, watch_parent


def test_pid_alive_self_true():
    assert pid_alive(os.getpid()) is True


def test_pid_alive_bogus_false():
    assert pid_alive(2**22 + 12345) is False  # 존재할 수 없는 PID
    assert pid_alive(-1) is False
    assert pid_alive("abc") is False
    assert pid_alive(None) is False


def test_watch_parent_fires_on_dead(monkeypatch):
    fired = threading.Event()
    state = {"alive": True}
    t = watch_parent(alive=lambda: state["alive"], on_dead=fired.set, interval_s=0.01)
    time.sleep(0.05)
    assert not fired.is_set()           # 살아있는 동안은 침묵
    state["alive"] = False
    assert fired.wait(timeout=2.0)      # 죽으면 콜백
    t.join(timeout=2.0)


def test_watch_parent_callback_error_safe(monkeypatch):
    # on_dead가 터져도 os._exit 폴백으로 가야 한다(여기선 패치로 관찰만).
    exited = threading.Event()
    monkeypatch.setattr(os, "_exit", lambda code: exited.set())

    def boom():
        raise RuntimeError("cleanup failed")

    watch_parent(alive=lambda: False, on_dead=boom, interval_s=0.01)
    assert exited.wait(timeout=2.0)
