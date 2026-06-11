"""윈도우/크로스플랫폼 화면 제어 실행기 — pyautogui(마우스·키보드) + mss(캡처).
맥은 기존 cliclick/screencapture 경로를 쓰므로 이 모듈은 비-맥에서만 호출된다.
주입형(테스트는 가짜 pyautogui/mss)."""
from __future__ import annotations
from pathlib import Path
from typing import Any

# cliclick 특수키 이름 → pyautogui 키 이름 매핑(일부)
_KEY_MAP = {"return": "enter", "esc": "escape", "arrow-up": "up", "arrow-down": "down",
            "arrow-left": "left", "arrow-right": "right", "page-up": "pageup",
            "page-down": "pagedown"}


def perform(action: str, x: Any = None, y: Any = None, text: str = "", key: str = "",
            amount: Any = None, gui: Any = None) -> bool:
    """동작 실행. 성공 True. gui 주입 가능(기본 pyautogui import). 예외는 호출부로."""
    g = gui
    if g is None:
        import pyautogui as g  # noqa: N811
    if action == "click":
        g.click(int(x), int(y))
    elif action == "double_click":
        g.doubleClick(int(x), int(y))
    elif action == "right_click":
        g.rightClick(int(x), int(y))
    elif action == "move":
        g.moveTo(int(x), int(y))
    elif action == "type":
        g.typewrite(str(text), interval=0.01)
    elif action == "key":
        g.press(_KEY_MAP.get(key.strip(), key.strip()))
    elif action == "scroll":
        g.scroll(int(amount) * 100)  # pyautogui scroll: 양수 위, 음수 아래
    else:
        return False
    return True


def capture(path: Path, grabber: Any = None) -> bool:
    """전체 화면을 path에 PNG로 저장. grabber 주입 가능(기본 mss)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if grabber is not None:
        return bool(grabber(path))
    import mss, mss.tools
    with mss.mss() as sct:
        shot = sct.grab(sct.monitors[0])
        mss.tools.to_png(shot.rgb, shot.size, output=str(path))
    return True
