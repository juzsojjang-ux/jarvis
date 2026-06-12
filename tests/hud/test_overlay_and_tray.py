"""HUD 오버레이 플랫폼 분기 + Windows 오버레이 + 상태 트레이 + 자막 CSS 픽스 테스트."""
from __future__ import annotations

import os
from pathlib import Path

import jarvis.__main__ as m
import jarvis.hud.overlay_win as ow
import jarvis.hud.tray as tray


class _FakePopen:
    last = None

    def __init__(self, args, *a, **k):
        _FakePopen.last = list(args)

    def poll(self):
        return None

    def terminate(self):
        pass


# --- _spawn_overlay 플랫폼 분기 ----------------------------------------------
def test_spawn_overlay_windows_uses_win_module(monkeypatch):
    monkeypatch.setattr(m.subprocess, "Popen", _FakePopen)
    monkeypatch.setattr(m.sys, "platform", "win32")
    m._spawn_overlay("http://127.0.0.1:8787/")
    assert "jarvis.hud.overlay_win" in _FakePopen.last
    assert "http://127.0.0.1:8787/" in _FakePopen.last


def test_spawn_overlay_mac_uses_mac_module(monkeypatch):
    monkeypatch.setattr(m.subprocess, "Popen", _FakePopen)
    monkeypatch.setattr(m.sys, "platform", "darwin")
    m._spawn_overlay("http://127.0.0.1:8787/")
    assert "jarvis.hud.overlay_mac" in _FakePopen.last


def test_spawn_tray_passes_parent_pid(monkeypatch):
    monkeypatch.setattr(m.subprocess, "Popen", _FakePopen)
    m._spawn_tray()
    assert "jarvis.hud.tray" in _FakePopen.last
    assert str(os.getpid()) in _FakePopen.last


# --- Windows 오버레이: 브라우저 탐색 + 앱 모드 커맨드 -------------------------
def test_find_browser_prefers_edge(monkeypatch):
    monkeypatch.setattr(ow.shutil, "which",
                        lambda n: r"C:\edge\msedge.exe" if n.startswith("msedge") else None)
    assert ow._find_browser() == r"C:\edge\msedge.exe"


def test_find_browser_none_when_absent(monkeypatch):
    monkeypatch.setattr(ow.shutil, "which", lambda n: None)
    monkeypatch.setattr(ow.os.path, "exists", lambda p: False)
    assert ow._find_browser() is None


def test_browser_app_cmd_is_app_mode_not_tab():
    cmd = ow._browser_app_cmd("http://127.0.0.1:8787/", "msedge")
    assert cmd[0] == "msedge"
    assert any(a == "--app=http://127.0.0.1:8787/" for a in cmd)  # 전용 창
    # 탭/일반창 플래그가 아니어야 함
    assert not any("--new-tab" in a or "--new-window" in a for a in cmd)


# --- 상태 트레이 아이콘 -------------------------------------------------------
def test_tray_icon_image_builds():
    im = tray._icon_image(48)
    assert im.size == (48, 48)
    assert im.mode == "RGBA"


def test_tray_terminate_parent_signals_pid(monkeypatch):
    calls = []
    monkeypatch.setattr(tray.os, "kill", lambda pid, sig: calls.append((pid, sig)))
    tray._terminate_parent(4321)
    assert calls and calls[0][0] == 4321


def test_tray_terminate_parent_noop_when_none(monkeypatch):
    calls = []
    monkeypatch.setattr(tray.os, "kill", lambda *a: calls.append(a))
    tray._terminate_parent(None)
    assert calls == []


# --- 자막 CSS 픽스(개인용·배포 공통) -----------------------------------------
def test_orb_html_korean_wrap_and_netflix_box():
    html = (Path(__file__).resolve().parents[2] / "jarvis" / "hud" / "orb.html").read_text(
        encoding="utf-8")
    # 한국어 어절 단위 줄바꿈(음절 중간 안 끊김)
    assert "word-break: keep-all" in html
    # 넷플릭스풍 검정 박스 + 줄마다 박스
    assert "box-decoration-break: clone" in html
    assert "#subtext" in html and 'id="subtext"' in html
    # 자막 텍스트는 박스 span에 주입
    assert "subTextEl.textContent" in html
