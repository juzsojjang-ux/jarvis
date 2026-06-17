"""Ask 입력창 전용 창 — 오브 오버레이와 달리 '포커스 가능·입력 가능'한 작은 앱모드 창.
크로미엄 --app 모드(탭/주소창 없는 전용 창)로 띄운다. 자체 프로세스로 실행:
    <python> -m jarvis.hud.ask_overlay http://127.0.0.1:8787/ask
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

_W, _H = 460, 380


def _chromium() -> str | None:
    names = (("msedge", "chrome") if sys.platform.startswith("win")
             else ("Google Chrome", "Microsoft Edge", "Chromium", "Brave Browser"))
    if sys.platform == "darwin":
        for app in ("Google Chrome", "Microsoft Edge", "Chromium", "Brave Browser"):
            p = f"/Applications/{app}.app/Contents/MacOS/{app}"
            if os.path.exists(p):
                return p
        return None
    for exe in names:
        p = shutil.which(exe) or shutil.which(exe + ".exe")
        if p:
            return p
    for c in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe"):
        if os.path.exists(c):
            return c
    return None


def main(url: str) -> int:
    browser = _chromium()
    if browser is None:
        print("[타자] 크로미엄 브라우저를 찾지 못해 입력창을 띄울 수 없습니다.")
        return 1
    prof = os.path.expanduser("~/.jarvis/ask_profile")
    args = [browser, f"--app={url}", f"--window-size={_W},{_H}",
            f"--user-data-dir={prof}", "--no-first-run", "--no-default-browser-check"]
    try:
        subprocess.run(args)
        return 0
    except OSError as exc:
        print(f"[타자] 입력창 실행 실패: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8787/ask"))
