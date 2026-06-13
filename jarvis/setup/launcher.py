"""첫 실행 설정 런처 — 브라우저를 열고 사용자가 완료할 때까지 대기한다."""
from __future__ import annotations

import subprocess
import sys
import webbrowser
from collections.abc import Callable

from .server import SetupServer


def _open_browser(url: str) -> bool:
    """브라우저를 연다. frozen .app에서는 webbrowser.open이 True만 반환하고 실제로는
    안 여는 경우가 있어(첫 설정이 무반응처럼 보임), 플랫폼 네이티브 명령을 먼저 쓴다."""
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", url], check=True, timeout=10)
            return True
        if sys.platform.startswith("win"):
            subprocess.run(["cmd", "/c", "start", "", url], check=True, timeout=10)
            return True
        subprocess.run(["xdg-open", url], check=True, timeout=10)
        return True
    except Exception:  # noqa: BLE001 - 네이티브 실패 시 webbrowser로 폴백
        try:
            return bool(webbrowser.open(url))
        except Exception:  # noqa: BLE001
            return False


def run_first_run_setup(
    opener: Callable[[str], None] | None = None,
    server_factory: Callable[[], SetupServer] | None = None,
) -> str:
    """설정 UI를 실행하고 선택된 provider 이름을 반환한다.

    opener   — 브라우저 열기 콜백(기본: 네이티브 open → webbrowser). 주입 가능.
    server_factory — SetupServer 생성 콜백. 테스트에서 가짜 서버 주입 가능.
    """
    open_fn = opener or _open_browser
    make = server_factory or (lambda: SetupServer())
    server = make()
    server.start()
    # 자동 열기 실패해도 직접 열 수 있게 주소를 크게 찍는다.
    print("\n" + "=" * 58)
    print("  자비스 첫 설정 — 브라우저에서 아래 주소를 여세요:")
    print(f"  >>>  {server.url}  <<<")
    print("  (이 창은 자비스 본체입니다. 끄지 마세요 — 설정을 마치면 이어서 켜집니다.)")
    print("=" * 58 + "\n", flush=True)
    try:
        opened = open_fn(server.url)
    except Exception:  # noqa: BLE001
        opened = False
    if not opened:
        print(f"[설정] 브라우저를 자동으로 열지 못했습니다 — 위 주소를 직접 여세요: {server.url}",
              flush=True)
    server.done.wait()
    server.stop()
    return server.chosen or "claude"


def run_settings(opener: Callable[[str], None] | None = None) -> None:
    """설정 변경 UI — 첫 실행 이후 보이스/마이크 키/두뇌/이름을 바꾼다(별도 프로세스).
    현재 값을 채워 보여주고, 저장하면 setup.json에 기록한다(재시작 시 적용)."""
    open_fn = opener or _open_browser
    server = SetupServer(settings_mode=True)
    server.start()
    print("\n" + "=" * 58)
    print("  자비스 설정 — 브라우저에서 아래 주소를 여세요:")
    print(f"  >>>  {server.url}  <<<")
    print("=" * 58 + "\n", flush=True)
    try:
        if not open_fn(server.url):
            print(f"[설정] 위 주소를 직접 여세요: {server.url}", flush=True)
    except Exception:  # noqa: BLE001
        pass
    server.done.wait()
    server.stop()
