"""조준 보조(click_by_name / ui_click_action) — 이름으로 요소 클릭.
맥 전용 AX 로직을 fake runner로 검증 — OS 무관하게 _is_mac을 참으로 고정."""
from __future__ import annotations

import pytest

import jarvis.tools.jarvis_mcp as jm
from jarvis.tools.jarvis_mcp import ui_click_action


@pytest.fixture(autouse=True)
def _force_mac_branch(monkeypatch):
    monkeypatch.setattr(jm, "_is_mac", lambda: True)


class _OnGate:
    def is_on(self):
        return True


class _OffGate:
    def is_on(self):
        return False


def _runner_returning(out):
    calls = []

    def runner(cmd, **kw):
        calls.append(cmd)

        class R:
            stdout = out if cmd[0] == "osascript" else ""
            returncode = 0
        return R()
    return runner, calls


def test_gate_off_refuses():
    out = ui_click_action("새로 만들기", gate=_OffGate())
    assert "꺼져" in out


def test_empty_name():
    assert "이름" in ui_click_action("", gate=_OnGate())


def test_axpress_success():
    runner, _ = _runner_returning("PRESSED:새로 만들기")
    out = ui_click_action("새로 만들기", gate=_OnGate(), runner=runner)
    assert "눌렀" in out and "새로 만들기" in out


def test_pos_fallback_clicks_coords():
    runner, calls = _runner_returning("POS:120,118")
    out = ui_click_action("파일 업로드", gate=_OnGate(), runner=runner)
    assert "눌렀" in out
    # osascript 다음에 cliclick으로 좌표 클릭이 일어났는지
    assert any(c[0] == "cliclick" and "c:120,118" in c[1] for c in calls)


def test_not_found_guides_fallback():
    runner, _ = _runner_returning("NOTFOUND")
    out = ui_click_action("없는버튼", gate=_OnGate(), runner=runner)
    assert "못 찾" in out and "screen_control" in out


def test_no_window():
    runner, _ = _runner_returning("NOWIN")
    out = ui_click_action("x", gate=_OnGate(), runner=runner)
    assert "활성 창" in out
