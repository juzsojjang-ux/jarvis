"""웹 드라이브(CDP) — 가짜 전송으로 프로토콜 로직 검증(실크롬 없이)."""
from __future__ import annotations

import asyncio
import json

from jarvis.tools.webdrive import WebDriver


class FakeWS:
    """CDP 웹소켓 흉내 — method별 핸들러로 응답."""
    def __init__(self, handlers):
        self.handlers = handlers
        self.sent = []
        self._queue = []

    async def send(self, raw):
        msg = json.loads(raw)
        self.sent.append(msg)
        result = self.handlers.get(msg["method"], lambda p: {})(msg.get("params", {}))
        self._queue.append(json.dumps({"id": msg["id"], "result": result}))

    async def recv(self):
        return self._queue.pop(0)

    async def close(self):
        pass


def _driver(handlers):
    ws = FakeWS(handlers)
    d = WebDriver(
        launcher=lambda: True,
        http_get=lambda path: ({"ok": 1} if path == "/json/version"
                               else [{"type": "page", "webSocketDebuggerUrl": "ws://x"}]),
        connect=None,
    )
    async def connect(url):
        return ws
    d._connect = connect
    return d, ws


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def _eval_result(value):
    return {"result": {"value": value}}


def test_read_returns_title_and_elements():
    snap = json.dumps({"title": "드라이브", "url": "https://drive.google.com",
                       "els": ["[0] button: 신규", "[1] a: 내 드라이브"]})
    d, ws = _driver({"Runtime.evaluate": lambda p: _eval_result(snap)})
    out = run(d.read())
    assert "드라이브" in out and "[0] button: 신규" in out


def test_click_unknown_index_guides():
    d, ws = _driver({"Runtime.evaluate": lambda p: _eval_result(False)})
    out = run(d.click(7))
    assert "[7]" in out and "web_read" in out


def test_type_sets_value_and_enter():
    calls = []
    def ev(p):
        calls.append(p.get("expression", ""))
        return _eval_result(True)
    d, ws = _driver({"Runtime.evaluate": ev,
                     "Input.dispatchKeyEvent": lambda p: {}})
    out = run(d.type(2, "자비스 테스트", submit=True))
    assert "입력했습니다" in out and "Enter" in out
    assert any("자비스 테스트" in c for c in calls)
    keys = [m for m in ws.sent if m["method"] == "Input.dispatchKeyEvent"]
    assert len(keys) == 2  # down + up


def test_upload_rejects_missing_files(tmp_path):
    d, ws = _driver({"Runtime.evaluate": lambda p: _eval_result(True)})
    out = run(d.upload(0, [str(tmp_path / "없는파일.zip")]))
    assert "파일이 없습니다" in out


def test_upload_sets_file_input(tmp_path):
    f = tmp_path / "배포.zip"
    f.write_bytes(b"x")
    def handlers():
        return {
            "Runtime.evaluate": lambda p: ({"result": {"objectId": "obj1"}}
                                           if "__jarvis_file_input" in p.get("expression", "")
                                           and "return" not in p.get("expression", "")
                                           else _eval_result(True)),
            "DOM.getDocument": lambda p: {"root": {"nodeId": 1}},
            "DOM.requestNode": lambda p: {"nodeId": 42},
            "DOM.setFileInputFiles": lambda p: {},
        }
    d, ws = _driver(handlers())
    out = run(d.upload(0, [str(f)]))
    assert "1개" in out
    setf = [m for m in ws.sent if m["method"] == "DOM.setFileInputFiles"]
    assert setf and setf[0]["params"]["nodeId"] == 42
    assert setf[0]["params"]["files"] == [str(f)]


def test_chrome_missing_message():
    d = WebDriver(launcher=lambda: False,
                  http_get=lambda path: (_ for _ in ()).throw(OSError("no chrome")))
    out = run(_safe(d.open("https://x.com")))
    assert "크롬" in out


async def _safe(coro):
    try:
        return await coro
    except Exception as exc:
        return str(exc)
