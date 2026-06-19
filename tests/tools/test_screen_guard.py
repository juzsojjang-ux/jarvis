"""_screen_guard 헬퍼 — TCC 권한 프리체크 단위 테스트.

helpers 자체만 테스트한다(@tool-wrapped 핸들러는 테스트하지 않음).
permissions 모듈 전체를 monkeypatch해서 OS 호출이 전혀 일어나지 않는다.
"""
from jarvis.tools import jarvis_mcp
from jarvis.core import permissions as P


def test_screen_guard_blocks_and_requests(monkeypatch):
    calls = []
    monkeypatch.setattr(P, "accessibility_trusted", lambda *a, **k: False)
    monkeypatch.setattr(P, "request_for", lambda cap, **k: calls.append(cap))
    msg = jarvis_mcp._screen_guard("accessibility")
    assert msg is not None and "손쉬운 사용" in msg
    assert calls == ["accessibility"]


def test_screen_guard_passes_when_granted(monkeypatch):
    monkeypatch.setattr(P, "screen_capture_trusted", lambda *a, **k: True)
    assert jarvis_mcp._screen_guard("screen") is None


def test_screen_guard_screen_blocked(monkeypatch):
    """screen 권한 막혔을 때 안내 문자열 + request_for 호출."""
    calls = []
    monkeypatch.setattr(P, "screen_capture_trusted", lambda *a, **k: False)
    monkeypatch.setattr(P, "request_for", lambda cap, **k: calls.append(cap))
    msg = jarvis_mcp._screen_guard("screen")
    assert msg is not None and "화면 기록" in msg
    assert calls == ["screen"]


def test_screen_guard_accessibility_passes(monkeypatch):
    """accessibility 권한 OK이면 None 반환."""
    monkeypatch.setattr(P, "accessibility_trusted", lambda *a, **k: True)
    assert jarvis_mcp._screen_guard("accessibility") is None
