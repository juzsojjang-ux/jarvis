"""웹 드라이브 — 자비스 전용 크롬 프로필을 CDP(DevTools 프로토콜)로 정밀 제어.

픽셀 클릭(screen_control)의 빗나감 문제를 끝낸다: DOM을 직접 읽고 누른다.
사용자의 평소 크롬은 절대 건드리지 않는다 — ~/.jarvis/chrome-profile 의
별도 브라우저를 띄우고, 구글 등 로그인은 사용자가 그 창에서 한 번만 해두면
세션이 유지된다(파일 업로드는 DOM.setFileInputFiles로 100% 결정적).

스냅샷 방식: 페이지의 상호작용 요소(링크/버튼/입력)를 번호 목록으로 뽑아
window.__jarvis_els 에 저장 → 두뇌가 번호로 click/type 한다.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any

PORT = 9333
PROFILE_DIR = Path.home() / ".jarvis" / "chrome-profile"
SHOT_PATH = Path.home() / ".jarvis" / "screenshots" / "web.png"

_SNAPSHOT_JS = r"""
(() => {
  const els = [...document.querySelectorAll(
    'a[href], button, input, textarea, select, [role="button"], [role="link"],' +
    '[role="menuitem"], [role="tab"], [contenteditable="true"]')]
    .filter(e => { const r = e.getBoundingClientRect();
                   return r.width > 1 && r.height > 1 &&
                          getComputedStyle(e).visibility !== 'hidden'; });
  window.__jarvis_els = els;
  const lab = e => {
    const t = (e.innerText || e.value || e.placeholder || e.getAttribute('aria-label')
               || e.title || e.alt || '').trim().replace(/\s+/g, ' ').slice(0, 60);
    const tag = e.tagName.toLowerCase();
    const type = e.type ? `/${e.type}` : '';
    return `${tag}${type}: ${t}`;
  };
  return JSON.stringify({
    title: document.title, url: location.href,
    els: els.slice(0, 120).map((e, i) => `[${i}] ${lab(e)}`)
  });
})()
"""


def _chrome_binary() -> str | None:
    candidates = (
        ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
        if sys.platform == "darwin" else
        [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
         r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
         os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe")]
        if os.name == "nt" else
        ["/usr/bin/google-chrome", "/usr/bin/chromium"])
    for c in candidates:
        if Path(c).exists():
            return c
    return None


class WebDriver:
    """페이지 1개 기준의 얇은 CDP 클라이언트(자비스 용도엔 충분)."""

    def __init__(self, port: int = PORT, launcher=None, http_get=None, connect=None):
        self._port = port
        self._launcher = launcher          # 주입 가능(테스트)
        self._http_get = http_get
        self._connect = connect            # async (ws_url) -> ws
        self._ws: Any = None
        self._msg_id = 0

    # ----- 브라우저 기동/연결 ------------------------------------------------
    def _get_json(self, path: str) -> Any:
        if self._http_get is not None:
            return self._http_get(path)
        with urllib.request.urlopen(f"http://127.0.0.1:{self._port}{path}", timeout=3) as r:
            return json.loads(r.read().decode())

    def _alive(self) -> bool:
        try:
            self._get_json("/json/version")
            return True
        except Exception:  # noqa: BLE001
            return False

    def _launch(self) -> bool:
        if self._launcher is not None:
            return bool(self._launcher())
        binary = _chrome_binary()
        if binary is None:
            return False
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(
            [binary, f"--remote-debugging-port={self._port}",
             f"--user-data-dir={PROFILE_DIR}", "--no-first-run",
             "--no-default-browser-check", "--new-window", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True

    async def _ensure(self) -> None:
        if self._ws is not None:
            try:
                await self._call("Runtime.evaluate", {"expression": "1"})
                return
            except Exception:  # noqa: BLE001 - 죽은 소켓: 재연결
                self._ws = None
        if not self._alive():
            if not self._launch():
                raise RuntimeError("크롬을 찾을 수 없습니다 — Chrome 설치가 필요합니다.")
            for _ in range(40):
                await asyncio.sleep(0.25)
                if self._alive():
                    break
            else:
                raise RuntimeError("자비스 크롬이 시간 안에 뜨지 않았습니다.")
        pages = [t for t in self._get_json("/json/list") if t.get("type") == "page"]
        if not pages:
            raise RuntimeError("크롬에 열린 페이지가 없습니다.")
        ws_url = pages[0]["webSocketDebuggerUrl"]
        if self._connect is not None:
            self._ws = await self._connect(ws_url)
        else:
            import websockets  # noqa: PLC0415
            self._ws = await websockets.connect(ws_url, max_size=40_000_000)

    async def _call(self, method: str, params: dict | None = None) -> dict:
        self._msg_id += 1
        mid = self._msg_id
        await self._ws.send(json.dumps({"id": mid, "method": method,
                                        "params": params or {}}))
        while True:
            raw = await asyncio.wait_for(self._ws.recv(), timeout=30)
            msg = json.loads(raw)
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(msg["error"].get("message", "CDP 오류"))
                return msg.get("result", {})

    async def _eval(self, js: str) -> Any:
        res = await self._call("Runtime.evaluate",
                               {"expression": js, "returnByValue": True,
                                "awaitPromise": True})
        return (res.get("result") or {}).get("value")

    # ----- 도구가 쓰는 동작들 ------------------------------------------------
    async def open(self, url: str) -> str:
        await self._ensure()
        await self._call("Page.navigate", {"url": url})
        await asyncio.sleep(2.0)
        return await self.read()

    async def read(self) -> str:
        await self._ensure()
        raw = await self._eval(_SNAPSHOT_JS)
        try:
            d = json.loads(raw)
        except Exception:  # noqa: BLE001
            return "페이지를 읽지 못했습니다."
        els = "\n".join(d.get("els", [])[:120])
        return f"{d.get('title', '')} — {d.get('url', '')}\n{els}"

    async def click(self, index: int) -> str:
        await self._ensure()
        ok = await self._eval(
            f"(()=>{{const e=window.__jarvis_els?.[{int(index)}];"
            f"if(!e)return false; e.scrollIntoView({{block:'center'}});"
            f"e.click(); return true;}})()")
        if not ok:
            return f"[{index}] 요소가 없습니다 — web_read로 목록을 다시 받으세요."
        await asyncio.sleep(1.2)
        return await self.read()

    async def type(self, index: int, text: str, submit: bool = False) -> str:
        await self._ensure()
        payload = json.dumps(text, ensure_ascii=False)
        ok = await self._eval(
            f"(()=>{{const e=window.__jarvis_els?.[{int(index)}]; if(!e)return false;"
            f"e.focus(); e.value={payload};"
            f"e.dispatchEvent(new Event('input',{{bubbles:true}}));"
            f"e.dispatchEvent(new Event('change',{{bubbles:true}})); return true;}})()")
        if not ok:
            return f"[{index}] 요소가 없습니다 — web_read로 목록을 다시 받으세요."
        if submit:
            await self._call("Input.dispatchKeyEvent",
                             {"type": "keyDown", "key": "Enter", "code": "Enter",
                              "windowsVirtualKeyCode": 13, "text": "\r"})
            await self._call("Input.dispatchKeyEvent",
                             {"type": "keyUp", "key": "Enter", "code": "Enter",
                              "windowsVirtualKeyCode": 13})
            await asyncio.sleep(1.2)
        return "입력했습니다." + ("" if not submit else " (Enter)")

    async def upload(self, index: int, paths: list[str]) -> str:
        """파일 업로드 — input[type=file] 요소에 결정적으로 파일을 꽂는다."""
        await self._ensure()
        files = [str(Path(p).expanduser()) for p in paths]
        missing = [f for f in files if not Path(f).exists()]
        if missing:
            return f"파일이 없습니다: {', '.join(missing)}"
        # __jarvis_els[index]가 file input이 아니면 가까운 input[type=file]을 찾는다
        ok = await self._eval(
            f"(()=>{{let e=window.__jarvis_els?.[{int(index)}]; if(!e)return false;"
            "if(e.tagName!=='INPUT'||e.type!=='file'){"
            "  e=document.querySelector('input[type=file]'); if(!e)return false;}"
            "window.__jarvis_file_input=e; return true;}})()")
        if not ok:
            return "파일 입력칸을 찾지 못했습니다 — 업로드 버튼을 먼저 web_click 해보세요."
        doc = await self._call("DOM.getDocument", {})
        root = doc["root"]["nodeId"]
        # 저장해둔 요소를 CDP 노드로 해석
        res = await self._call("Runtime.evaluate",
                               {"expression": "window.__jarvis_file_input"})
        obj_id = (res.get("result") or {}).get("objectId")
        node = await self._call("DOM.requestNode", {"objectId": obj_id})
        await self._call("DOM.setFileInputFiles",
                         {"files": files, "nodeId": node["nodeId"]})
        await asyncio.sleep(1.0)
        del root
        return (f"파일 {len(files)}개를 업로드 입력에 넣었습니다 — "
                "페이지의 업로드 진행을 web_read로 확인하세요.")

    async def screenshot(self) -> str:
        await self._ensure()
        res = await self._call("Page.captureScreenshot", {"format": "png"})
        SHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        SHOT_PATH.write_bytes(base64.b64decode(res["data"]))
        return str(SHOT_PATH)

    async def close(self) -> str:
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:  # noqa: BLE001
                pass
            self._ws = None
        return "웹 드라이브 연결을 닫았습니다(브라우저 창은 그대로)."


DRIVER = WebDriver()
