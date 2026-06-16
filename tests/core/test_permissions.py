"""tests/core/test_permissions.py — 권한 확인·요청 모듈.

실제 시스템 다이얼로그를 띄우지 않게 prompt=False 또는 monkeypatch로 격리한다.
"""
from __future__ import annotations

from jarvis.core import permissions


def test_non_mac_short_circuits(monkeypatch):
    monkeypatch.setattr(permissions, "_is_mac", lambda: False)
    assert permissions.accessibility_trusted(prompt=True) is True
    assert permissions.screen_capture_trusted() is True
    assert permissions.ensure_permissions() == {"accessibility": True, "screen": True}


def test_accessibility_trusted_returns_bool_without_prompt():
    # prompt=False라 다이얼로그를 띄우지 않고 상태만 본다.
    assert isinstance(permissions.accessibility_trusted(prompt=False), bool)


def test_ensure_permissions_all_granted(monkeypatch):
    monkeypatch.setattr(permissions, "_is_mac", lambda: True)
    monkeypatch.setattr(permissions, "accessibility_trusted", lambda prompt=False: True)
    monkeypatch.setattr(permissions, "screen_capture_trusted", lambda: True)
    assert permissions.ensure_permissions() == {"accessibility": True, "screen": True}


def test_ensure_permissions_missing_opens_settings_and_announces(monkeypatch):
    calls: list[str] = []
    msgs: list[str] = []
    monkeypatch.setattr(permissions, "_is_mac", lambda: True)
    monkeypatch.setattr(permissions, "accessibility_trusted", lambda prompt=False: False)
    monkeypatch.setattr(permissions, "screen_capture_trusted", lambda: True)
    monkeypatch.setattr(permissions, "open_settings_pane", lambda anchor: calls.append(anchor))
    r = permissions.ensure_permissions(announce=lambda m: msgs.append(m))
    assert r["accessibility"] is False
    assert "Privacy_Accessibility" in calls  # 설정 창을 열어 안내
    assert msgs and "손쉬운 사용" in msgs[0]   # 음성 안내 호출


def test_ensure_permissions_never_raises(monkeypatch):
    # accessibility_trusted가 터져도 ensure_permissions는 예외를 올리지 않는다.
    monkeypatch.setattr(permissions, "_is_mac", lambda: True)

    def _boom(prompt=False):
        raise RuntimeError("boom")

    monkeypatch.setattr(permissions, "accessibility_trusted", _boom)
    # ensure_permissions 내부는 accessibility_trusted를 직접 부르므로 예외가 샐 수 있다 →
    # 호출부(__main__)가 try/except로 감싸지만, 모듈 자체도 견고해야 한다.
    try:
        permissions.ensure_permissions()
    except Exception as e:  # noqa: BLE001
        raise AssertionError(f"ensure_permissions가 예외를 올림: {e}") from e
