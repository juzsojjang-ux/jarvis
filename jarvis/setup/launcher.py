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
    open_fn = opener or webbrowser.open
    make = server_factory or (lambda: SetupServer())
    server = make()
    server.start()
    print(f"[설정] 브라우저에서 다음 주소를 열어 두뇌를 선택하세요: {server.url}")
    try:
        opened = open_fn(server.url)
    except Exception:  # noqa: BLE001
        opened = False
    if not opened:
        print(f"[설정] 브라우저를 자동으로 열지 못했습니다. 위 주소를 직접 여세요: {server.url}")
    server.done.wait()
    server.stop()
    return server.chosen or "claude"
