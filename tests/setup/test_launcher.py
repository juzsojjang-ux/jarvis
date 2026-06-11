"""tests/setup/test_launcher.py — launcher.py 단위 테스트.

실제 브라우저, 실제 서버, 실제 keyring, 실제 ~/.jarvis 는 건드리지 않는다.
가짜 서버와 recording opener를 주입한다.
"""
from __future__ import annotations

import threading

import pytest

from jarvis.setup.launcher import run_first_run_setup


# ---------------------------------------------------------------------------
# 가짜 서버
# ---------------------------------------------------------------------------

class _FakeServer:
    """run_first_run_setup이 쓰는 서버 인터페이스를 흉내낸다."""

    def __init__(self, chosen: str = "gemini") -> None:
        self.done = threading.Event()
        self.chosen = chosen
        self.done.set()          # 이미 완료 상태 — wait()이 즉시 반환됨
        self._started = False
        self._stopped = False
        self.port = 59999
        self._host = "127.0.0.1"

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    def start(self) -> None:
        self._started = True

    def stop(self) -> None:
        self._stopped = True


# ---------------------------------------------------------------------------
# 테스트
# ---------------------------------------------------------------------------

def test_returns_chosen_provider():
    fake = _FakeServer(chosen="gemini")
    result = run_first_run_setup(
        opener=lambda url: None,
        server_factory=lambda: fake,
    )
    assert result == "gemini"


def test_opener_called_with_url():
    fake = _FakeServer(chosen="claude")
    opened_urls: list[str] = []

    run_first_run_setup(
        opener=lambda url: opened_urls.append(url),
        server_factory=lambda: fake,
    )

    assert len(opened_urls) == 1
    assert "127.0.0.1" in opened_urls[0]
    assert str(fake.port) in opened_urls[0]


def test_server_started_and_stopped():
    fake = _FakeServer(chosen="gpt")
    run_first_run_setup(
        opener=lambda url: None,
        server_factory=lambda: fake,
    )
    assert fake._started is True
    assert fake._stopped is True


def test_defaults_to_claude_when_chosen_is_none():
    class _NoChosenServer(_FakeServer):
        def __init__(self):
            super().__init__(chosen=None)

    run_first_run_setup(
        opener=lambda url: None,
        server_factory=_NoChosenServer,
    )
    # 결과가 None이 아닌 "claude"여야 한다
    result = run_first_run_setup(
        opener=lambda url: None,
        server_factory=_NoChosenServer,
    )
    assert result == "claude"
