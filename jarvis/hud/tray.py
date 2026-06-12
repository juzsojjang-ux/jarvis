"""'자비스 실행 중' 상태 아이콘 — macOS 메뉴 막대(와이파이 아이콘 옆) / Windows 시스템 트레이.

pystray로 양 플랫폼 모두에 작은 자비스 오브 아이콘을 띄운다. 자체 프로세스로 실행:
    <python> -m jarvis.hud.tray [parent_pid]
메뉴: '자비스 실행 중'(상태) + '자비스 종료'(parent_pid에 종료 신호).
pystray/Pillow가 없으면 조용히 생략(상태 아이콘은 옵션, 음성/부팅을 막지 않는다)."""
from __future__ import annotations

import os
import signal
import sys


def _icon_image(size: int = 64):
    """자비스 오브 느낌의 아이콘 — 시안 링 + 중앙 골드 점(투명 배경)."""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad, w = size * 0.10, max(3, int(size * 0.08))
    d.ellipse((pad, pad, size - pad, size - pad), outline=(80, 220, 255, 255), width=w)
    c0, c1 = size * 0.40, size * 0.60
    d.ellipse((c0, c0, c1, c1), fill=(236, 186, 79, 255))
    return img


def _terminate_parent(parent_pid) -> None:
    if not parent_pid:
        return
    try:
        # Windows에서도 os.kill(pid, SIGTERM)은 TerminateProcess로 동작한다.
        os.kill(int(parent_pid), signal.SIGTERM)
    except (OSError, ValueError):
        pass


def main(parent_pid=None) -> int:
    try:
        import pystray
    except Exception as exc:  # noqa: BLE001 - 상태 아이콘은 옵션
        print(f"[tray] pystray 미설치({exc}) — 상태 아이콘 생략.")
        return 1

    icon_holder = {}

    def _quit(icon, _item) -> None:
        icon.visible = False
        icon.stop()
        _terminate_parent(parent_pid)

    name = (os.environ.get("JARVIS_ASSISTANT_NAME") or "자비스").strip() or "자비스"
    menu = pystray.Menu(
        pystray.MenuItem(f"● {name} 실행 중", None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(f"{name} 종료", _quit),
    )
    try:
        icon = pystray.Icon("jarvis", _icon_image(), f"{name} — 실행 중", menu)
        icon_holder["icon"] = icon

        # 메인 자비스가 죽으면(kill -9/크래시 포함) 유령 아이콘으로 남지 않게 종료.
        def _self_destruct() -> None:
            try:
                icon.visible = False
                icon.stop()
            finally:
                os._exit(0)

        from jarvis.hud.procwatch import watch_parent
        watch_parent(parent_pid, _self_destruct)
        icon.run()
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"[tray] 상태 아이콘 실행 실패: {exc}")
        return 1


if __name__ == "__main__":
    pid = sys.argv[1] if len(sys.argv) > 1 else None
    raise SystemExit(main(pid))
