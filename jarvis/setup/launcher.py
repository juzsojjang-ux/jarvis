"""첫 실행 설정 런처 — 브라우저를 열고 사용자가 완료할 때까지 대기한다."""
from __future__ import annotations

import webbrowser
from typing import Callable

from .server import SetupServer


def run_first_run_setup(
    opener: Callable[[str], None] | None = None,
    server_factory: Callable[[], SetupServer] | None = None,
) -> str:
    """설정 UI를 실행하고 선택된 provider 이름을 반환한다.

    opener   — 브라우저 열기 콜백(기본: webbrowser.open). 테스트에서 주입 가능.
    server_factory — SetupServer 생성 콜백. 테스트에서 가짜 서버 주입 가능.
    """
    _opener = opener or webbrowser.open
    server = server_factory() if server_factory else SetupServer()

    server.start()
    try:
        _opener(server.url)
        server.done.wait()  # 사용자가 완료할 때까지 블록
    finally:
        server.stop()

    return server.chosen or "claude"
