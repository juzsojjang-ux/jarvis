"""Native Windows overlay hosting the JARVIS HUD — NO browser tab.

윈도우에서 HUD를 "인터넷(브라우저 탭)"이 아니라 전용 창으로 띄운다. 좋은 순서대로:

  1) pywebview (설치돼 있으면): 프레임 없는·항상 위·투명 창에 WebView2를 박아 HUD
     페이지를 띄운다 — macOS 오버레이에 가장 가까운 모습. 가능하면 WS_EX_TRANSPARENT|
     WS_EX_LAYERED(ctypes)로 클릭통과까지 적용해 마우스를 막지 않는다.
  2) 폴백(항상 가능): Microsoft Edge / Chrome 의 *앱 모드*(--app=URL). 탭도 주소창도
     없는 전용 테두리 창 — 진짜 앱 창이지, 브라우저 탭이 아니다. Windows 10/11이면
     Edge가 기본 내장이라 무설치로 동작한다.

자체 프로세스로 실행된다 — 오케스트레이터가 spawn:
    <python> -m jarvis.hud.overlay_win http://127.0.0.1:8787/
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

# HUD 전용 창 크기(앱 모드). orb는 뷰포트 중앙에 그려지고 자막은 하단에 깔린다.
_WIN_W, _WIN_H = 560, 600


def _find_browser() -> str | None:
    """앱 모드를 지원하는 크로미엄 계열 — Edge 우선, 없으면 Chrome."""
    for exe in ("msedge", "msedge.exe", "chrome", "chrome.exe"):
        p = shutil.which(exe)
        if p:
            return p
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def _browser_app_cmd(url: str, browser: str) -> list[str]:
    """크로미엄 앱 모드 커맨드 — 탭/주소창 없는 전용 창(브라우저 탭이 아님).

    메인 브라우저 세션과 섞이지 않게 전용 프로필(--user-data-dir)을 쓴다.
    """
    prof = os.path.join(os.path.expanduser("~"), ".jarvis", "hud-profile")
    return [
        browser,
        f"--app={url}",
        f"--user-data-dir={prof}",
        f"--window-size={_WIN_W},{_WIN_H}",
        "--window-position=40,40",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
    ]


def _run_pywebview(url: str) -> bool:
    """pywebview로 프레임 없는·항상 위·투명 오버레이. 성공 시 블로킹(창 닫힐 때까지).

    설치 안 됐거나 실패하면 False를 돌려 폴백(앱 모드)으로 넘긴다.
    """
    if os.environ.get("JARVIS_HUD_PYWEBVIEW", "1") == "0":
        return False
    try:
        import webview  # pywebview
    except Exception:
        return False
    try:
        webview.create_window(
            "JARVIS", url=url, frameless=True, on_top=True,
            transparent=True, background_color="#00000000",
            width=_WIN_W, height=_WIN_H, x=40, y=40,
            resizable=False, easy_drag=False,
        )

        def _clickthrough() -> None:
            # WS_EX_TRANSPARENT|WS_EX_LAYERED 로 클릭통과(가능할 때만, 실패해도 무해).
            try:
                import ctypes
                user32 = ctypes.windll.user32
                hwnd = user32.FindWindowW(None, "JARVIS")
                if hwnd:
                    GWL_EXSTYLE, WS_EX_LAYERED, WS_EX_TRANSPARENT = -20, 0x80000, 0x20
                    ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                    user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                                          ex | WS_EX_LAYERED | WS_EX_TRANSPARENT)
            except Exception:
                pass

        webview.start(_clickthrough)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[overlay] pywebview 실패({exc}) — 앱 모드로 폴백.")
        return False


def main(url: str) -> int:
    import importlib.util
    import time

    from jarvis.hud.procwatch import pid_alive, watch_parent

    ppid = os.getppid()  # 메인 자비스 — 죽으면 우리(와 앱 창)도 정리한다
    # pywebview 창은 '우리 프로세스 소유'라 부모가 죽으면 watch_parent의 기본 동작(os._exit)으로
    # 우리가 죽으면 창도 함께 닫힌다. 단 이 기본 워처는 '브라우저 Popen 창'은 못 닫는다 — 그래서
    # pywebview를 실제로 쓸 때(webview 설치 + 토글 ON)만 건다. 안 그러면 app 모드 폴백에서
    # 고아 브라우저 창이 남는다(audit high #10).
    use_pw = (os.environ.get("JARVIS_HUD_PYWEBVIEW", "1") != "0"
              and importlib.util.find_spec("webview") is not None)
    if use_pw:
        watch_parent(ppid)
        if _run_pywebview(url):
            return 0
    browser = _find_browser()
    if not browser:
        print("[overlay] Edge/Chrome를 찾지 못했습니다. HUD를 브라우저로 열려면 "
              f"직접 {url} 을 여세요.")
        return 1
    try:
        proc = subprocess.Popen(_browser_app_cmd(url, browser))
        print("[HUD] 전용 창으로 자비스 인터페이스를 띄웠습니다(브라우저 탭 아님).")
    except OSError as exc:
        print(f"[overlay] 앱 모드 실행 실패: {exc}")
        return 1

    # 앱 모드: 부모가 죽으면 '브라우저 창까지' 닫고 종료한다(고아 HUD 방지).
    def _on_parent_dead() -> None:
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass
        os._exit(0)

    watch_parent(ppid, on_dead=_on_parent_dead)
    # 창(브라우저)이 닫히면 우리도 끝낸다.
    while True:
        if proc.poll() is not None:
            return 0
        if not pid_alive(ppid):       # 워처가 먼저 잡지만, 안전망으로 한 번 더 확인
            _on_parent_dead()
        time.sleep(2.0)


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8787/"
    raise SystemExit(main(target))
