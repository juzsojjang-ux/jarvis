"""아이폰 원격 명령 수신 — orb_server처럼 stdlib 스레드 HTTP(의존성 0).

핸들러는 주입된다: __main__이 asyncio 루프로 던지는 브리지를 넣는다(이 모듈은
asyncio를 모른다). 인증 실패는 본문 없는 401(정보 누설 금지). 어떤 실패도
부팅·음성 파이프라인을 깨지 않는다."""
from __future__ import annotations

import hmac
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class RemoteServer:
    def __init__(self, handler, host: str, port: int, token: str) -> None:
        self._handler = handler  # (text: str) -> dict — 스레드에서 블로킹 호출
        self._host = host
        self.port = port  # start() 후 실제 바인드 포트로 갱신(테스트는 0 사용)
        self._token = token
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._last_auth_log = 0.0

    @property
    def url(self) -> str:
        return f"http://{self._host}:{self.port}/ask"

    def start(self) -> None:
        outer = self

        class _Handler(BaseHTTPRequestHandler):
            timeout = 30  # 느린/반열림 연결이 스레드를 영원히 잡는 것 방지

            def log_message(self, *args):  # noqa: D102 - stderr 스팸 방지
                pass

            def _send(self, code: int, payload: dict | None = None) -> None:
                body = (b"" if payload is None
                        else json.dumps(payload, ensure_ascii=False).encode("utf-8"))
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if body:
                    self.wfile.write(body)

            def do_POST(self):  # noqa: N802 - http.server 계약
                # 인증을 경로 확인보다 먼저 — 경로 탐색으로 엔드포인트 존재를 확인할 수 없다(N1).
                auth = self.headers.get("Authorization", "")
                if not hmac.compare_digest(auth, f"Bearer {outer._token}"):
                    now = time.monotonic()
                    if now - outer._last_auth_log > 10.0:
                        outer._last_auth_log = now
                        print("[원격] 인증 실패 요청 거부")
                    self._send(401)
                    return
                if self.path != "/ask":
                    self._send(404, {"reply": "없는 경로입니다."})
                    return
                try:
                    n = int(self.headers.get("Content-Length", "0"))
                    if n > 64 * 1024:
                        self._send(413, {"reply": "요청이 너무 큽니다."})
                        return
                    data = json.loads(self.rfile.read(n) or b"{}")
                    text = str(data.get("text", "")).strip()
                except Exception:  # noqa: BLE001 - 못 읽는 본문은 빈 text 취급
                    text = ""
                if not text:
                    self._send(400, {"reply": "text가 비어 있습니다."})
                    return
                try:
                    result = outer._handler(text)
                except TimeoutError:
                    self._send(504, {"reply": "응답이 너무 오래 걸립니다."})
                    return
                except Exception:  # noqa: BLE001 - 핸들러 실패는 500으로 격리
                    self._send(500, {"reply": "처리 중 오류가 났습니다."})
                    return
                self._send(200, result)

            def do_GET(self):  # noqa: N802 - http.server 계약
                self._send(404, {"reply": "없는 경로입니다."})

        self._httpd = ThreadingHTTPServer((self._host, self.port), _Handler)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        name="jarvis-remote", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
