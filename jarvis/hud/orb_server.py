"""Dependency-free localhost server for the JARVIS orb HUD.

Serves orb.html on ``/`` and a Server-Sent-Events stream on ``/events``. The
orchestrator calls ``OrbServer.publish(state, level)`` on every state change; each
connected browser receives it via the native EventSource API and animates the orb.
Stdlib only (http.server + threads) so it adds no install footprint and never blocks
the asyncio pipeline. All publishing is best-effort: the HUD must never break voice.
"""
from __future__ import annotations

import json
import queue
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ORB_HTML = Path(__file__).resolve().parent / "orb.html"


def _orb_asset_path():
    mp = getattr(sys, "_MEIPASS", None)
    if mp:
        p = Path(mp) / "jarvis" / "hud" / "assets" / "orb.mp4"
        if p.exists():
            return p
    return Path(__file__).resolve().parent / "assets" / "orb.mp4"


def _apply_assistant_name(body: bytes) -> bytes:
    """이름 변경 반영 — orb.html의 'J.A.R.V.I.S' 라벨을 설정된 이름으로 치환.
    영문 이름은 점 구분 대문자(F.R.I.D.A.Y 풍), 한글 등은 그대로 표시한다."""
    import os
    name = (os.environ.get("JARVIS_ASSISTANT_NAME") or "").strip()
    if not name or name == "자비스":
        return body
    display = ".".join(name.upper()) if name.isascii() and name.isalpha() else name
    return body.replace(b"J.A.R.V.I.S", display.encode("utf-8"))
_VALID_STATES = ("idle", "attentive", "listening", "thinking", "speaking")


class OrbHub:
    """Fan-out of {state, level} events to connected SSE clients (thread-safe)."""

    def __init__(self) -> None:
        self._clients: set[queue.Queue] = set()
        self._lock = threading.Lock()
        self._text = ""  # current on-screen subtitle (Korean), persists across level pumps
        self._notice = ""  # 우측 상단 알림(진행중/확인필요/오류) — 명시적으로 비울 때까지 유지
        self._expand = False  # A↔B 전환 상태(sticky) — 명시적으로 바꿀 때까지 유지
        self._last = {"state": "idle", "level": 0.0, "text": "", "notice": "", "expand": False}

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=64)
        with self._lock:
            self._clients.add(q)
        q.put(dict(self._last))  # replay current state immediately on connect
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            self._clients.discard(q)

    def publish(self, state: str, level: float = 0.0, text: str | None = None,
                notice: str | None = None, expand: bool | None = None) -> dict:
        if state not in _VALID_STATES:
            state = "idle"
        # Subtitle lifecycle: set when given; cleared whenever JARVIS isn't speaking.
        if text is not None:
            self._text = text
        if state != "speaking":
            self._text = ""
        if notice is not None:
            self._notice = notice
        if expand is not None:
            self._expand = bool(expand)
        return self._emit(state, level)

    def publish_notice(self, notice: str | None) -> dict:
        """우측 상단 알림만 갱신(현재 상태/자막은 그대로 유지)."""
        self._notice = notice or ""
        last = self._last
        return self._emit(last.get("state", "idle"), last.get("level", 0.0))

    def _emit(self, state: str, level: float) -> dict:
        evt = {"state": state, "level": round(max(0.0, min(1.0, float(level))), 4),
               "text": self._text, "notice": self._notice, "expand": self._expand}
        self._last = evt
        with self._lock:
            clients = list(self._clients)
        for q in clients:
            try:
                q.put_nowait(dict(evt))
            except queue.Full:
                pass
        return evt

    def client_count(self) -> int:
        with self._lock:
            return len(self._clients)


def _make_handler(hub: OrbHub):
    class OrbHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args) -> None:  # silence default stderr spam
            pass

        def do_GET(self) -> None:  # noqa: N802 (stdlib name)
            path = self.path.split("?", 1)[0]
            if path.startswith("/events"):
                self._serve_events()
            elif path in ("/", "/index.html", "/orb.html"):
                self._serve_html()
            elif path == "/assets/orb.mp4":
                try:
                    data = _orb_asset_path().read_bytes()
                except Exception:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "max-age=86400")
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass  # client cancelled mid-stream (e.g. browser seeking video)
            elif path == "/health":
                self._serve_bytes(b"ok", "text/plain; charset=utf-8")
            elif path == "/favicon.ico":
                self.send_response(204)
                self.send_header("Content-Length", "0")
                self.end_headers()
            else:
                self.send_error(404)

        def _serve_html(self) -> None:
            try:
                body = ORB_HTML.read_bytes()
            except OSError:
                self.send_error(500)
                return
            body = _apply_assistant_name(body)
            self._serve_bytes(body, "text/html; charset=utf-8")

        def _serve_bytes(self, body: bytes, ctype: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _serve_events(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            q = hub.subscribe()
            try:
                while True:
                    try:
                        evt = q.get(timeout=15)
                        chunk = f"data: {json.dumps(evt)}\n\n".encode()
                    except queue.Empty:
                        chunk = b": keep-alive\n\n"  # SSE comment ping
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                hub.unsubscribe(q)

    return OrbHandler


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class OrbServer:
    """Background HTTP/SSE server for the orb. start() is non-blocking; publish() is
    safe to call from any thread (the orchestrator calls it from the asyncio loop)."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8787) -> None:
        self.host = host
        self.port = port
        self.hub = OrbHub()
        self._httpd: _Server | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    def start(self) -> None:
        self._httpd = _Server((self.host, self.port), _make_handler(self.hub))
        self.port = self._httpd.server_address[1]  # reflect the real port (handles port=0)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def publish(self, state: str, level: float = 0.0, text: str | None = None,
                notice: str | None = None, expand: bool | None = None) -> None:
        self.hub.publish(state, level, text, notice, expand)

    def publish_notice(self, notice: str | None) -> None:
        self.hub.publish_notice(notice)

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
