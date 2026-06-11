"""첫 실행 설정 서버 — stdlib ThreadingHTTPServer(orb_server 패턴 재사용).

GET /  → 설정 HTML 페이지(SETUP_HTML 인라인 상수).
POST /setup JSON {provider, key?} → 검증 후 저장, 완료 이벤트 set.

validator(provider, key) → (ok, msg) 비동기: 테스트에서 주입 가능.
store_save(provider, key) → None: 테스트에서 주입 가능.
"""
from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from .validate import validate as _default_validate
from .store import save_key, save_setup

# ---------------------------------------------------------------------------
# 설정 HTML — 영화풍 다크 테마, 세 카드, 한국어 레이블
# ---------------------------------------------------------------------------

SETUP_HTML = """\
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>자비스 — 첫 실행 설정</title>
<style>
  :root {
    --bg: #0a0c10;
    --surface: #111520;
    --border: #1e2a3a;
    --accent: #00d4ff;
    --accent2: #0090cc;
    --text: #c8d8e8;
    --dim: #5a7080;
    --ok: #00e08a;
    --fail: #ff4455;
    --card-selected: #0d2035;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, "SF Pro Display", "Segoe UI", sans-serif;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 2rem 1rem;
  }
  .header {
    text-align: center;
    margin-bottom: 2.5rem;
  }
  .header h1 {
    font-size: 2rem;
    font-weight: 300;
    letter-spacing: 0.25em;
    color: var(--accent);
    text-transform: uppercase;
  }
  .header p {
    margin-top: 0.5rem;
    color: var(--dim);
    font-size: 0.9rem;
    letter-spacing: 0.05em;
  }
  .cards {
    display: flex;
    gap: 1rem;
    flex-wrap: wrap;
    justify-content: center;
    margin-bottom: 2rem;
  }
  .card {
    border: 1px solid var(--border);
    border-radius: 10px;
    background: var(--surface);
    padding: 1.5rem 1.8rem;
    width: 200px;
    cursor: pointer;
    transition: border-color 0.2s, background 0.2s;
    user-select: none;
    position: relative;
  }
  .card:hover { border-color: var(--accent2); }
  .card.selected {
    border-color: var(--accent);
    background: var(--card-selected);
    box-shadow: 0 0 12px rgba(0,212,255,0.15);
  }
  .card .provider-name {
    font-size: 1.1rem;
    font-weight: 600;
    letter-spacing: 0.05em;
    color: var(--accent);
    margin-bottom: 0.4rem;
  }
  .card .provider-note {
    font-size: 0.78rem;
    color: var(--dim);
    line-height: 1.4;
  }
  .card input[type="radio"] { display: none; }
  .key-section {
    width: 100%;
    max-width: 440px;
    margin-bottom: 1.5rem;
    display: none;
  }
  .key-section.visible { display: block; }
  .key-section label {
    display: block;
    font-size: 0.82rem;
    color: var(--dim);
    margin-bottom: 0.5rem;
    letter-spacing: 0.04em;
  }
  .key-section input[type="text"] {
    width: 100%;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    padding: 0.7rem 1rem;
    font-size: 0.95rem;
    outline: none;
    transition: border-color 0.2s;
    font-family: "SF Mono", "Menlo", monospace;
  }
  .key-section input[type="text"]:focus { border-color: var(--accent); }
  .btn-start {
    background: linear-gradient(135deg, var(--accent2), var(--accent));
    color: #000;
    font-weight: 700;
    font-size: 1rem;
    letter-spacing: 0.08em;
    border: none;
    border-radius: 8px;
    padding: 0.75rem 3rem;
    cursor: pointer;
    text-transform: uppercase;
    transition: opacity 0.2s;
  }
  .btn-start:hover { opacity: 0.85; }
  .btn-start:disabled { opacity: 0.4; cursor: default; }
  #msg {
    margin-top: 1.2rem;
    min-height: 1.4em;
    font-size: 0.9rem;
    text-align: center;
    transition: color 0.2s;
  }
  #msg.ok { color: var(--ok); }
  #msg.fail { color: var(--fail); }
  .done-box {
    display: none;
    flex-direction: column;
    align-items: center;
    gap: 0.6rem;
    margin-top: 1.5rem;
  }
  .done-box.visible { display: flex; }
  .done-box .checkmark { font-size: 2.5rem; }
  .done-box p { color: var(--ok); font-size: 1rem; letter-spacing: 0.04em; }
  .done-box small { color: var(--dim); font-size: 0.8rem; }
</style>
</head>
<body>

<div class="header">
  <h1>J.A.R.V.I.S</h1>
  <p>두뇌를 선택하여 초기 설정을 완료하세요</p>
</div>

<div class="cards" id="cards">

  <label class="card selected" data-provider="claude">
    <input type="radio" name="provider" value="claude" checked>
    <div class="provider-name">Claude</div>
    <div class="provider-note">구독 로그인 사용<br>(키 불필요)</div>
  </label>

  <label class="card" data-provider="gemini">
    <input type="radio" name="provider" value="gemini">
    <div class="provider-name">Gemini</div>
    <div class="provider-note">Google AI Studio 키</div>
  </label>

  <label class="card" data-provider="gpt">
    <input type="radio" name="provider" value="gpt">
    <div class="provider-name">GPT</div>
    <div class="provider-note">OpenAI 키</div>
  </label>

</div>

<div class="key-section" id="keySection">
  <label id="keyLabel">API 키</label>
  <input type="text" id="keyInput" placeholder="키를 여기에 붙여넣으세요" autocomplete="off" spellcheck="false">
</div>

<button class="btn-start" id="btnStart">시작</button>

<div id="msg"></div>

<div class="done-box" id="doneBox">
  <div class="checkmark">✓</div>
  <p>설정 완료 — 자비스를 시작합니다</p>
  <small>이 창을 닫으셔도 됩니다</small>
</div>

<script>
(function () {
  const cards = document.querySelectorAll('.card');
  const keySection = document.getElementById('keySection');
  const keyLabel = document.getElementById('keyLabel');
  const keyInput = document.getElementById('keyInput');
  const btnStart = document.getElementById('btnStart');
  const msgEl = document.getElementById('msg');
  const doneBox = document.getElementById('doneBox');

  const KEY_LABELS = {
    gemini: 'Google AI Studio API 키',
    gpt: 'OpenAI API 키',
  };

  function selectedProvider() {
    const checked = document.querySelector('input[name="provider"]:checked');
    return checked ? checked.value : 'claude';
  }

  function updateUI() {
    const prov = selectedProvider();
    cards.forEach(c => c.classList.toggle('selected', c.dataset.provider === prov));
    const needsKey = prov === 'gemini' || prov === 'gpt';
    keySection.classList.toggle('visible', needsKey);
    if (needsKey) {
      keyLabel.textContent = KEY_LABELS[prov] || 'API 키';
      keyInput.placeholder = '키를 여기에 붙여넣으세요';
    }
    msgEl.textContent = '';
    msgEl.className = '';
  }

  cards.forEach(card => {
    card.addEventListener('click', () => {
      const radio = card.querySelector('input[type="radio"]');
      radio.checked = true;
      updateUI();
    });
  });

  btnStart.addEventListener('click', async () => {
    const prov = selectedProvider();
    const key = keyInput.value.trim();
    msgEl.textContent = '검증 중…';
    msgEl.className = '';
    btnStart.disabled = true;

    try {
      const res = await fetch('/setup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider: prov, key }),
      });
      const data = await res.json();
      if (data.ok) {
        msgEl.textContent = data.message || '성공';
        msgEl.className = 'ok';
        doneBox.classList.add('visible');
        btnStart.disabled = true;
      } else {
        msgEl.textContent = data.error || '오류가 발생했습니다.';
        msgEl.className = 'fail';
        btnStart.disabled = false;
      }
    } catch (e) {
      msgEl.textContent = '서버에 연결할 수 없습니다.';
      msgEl.className = 'fail';
      btnStart.disabled = false;
    }
  });

  updateUI();
})();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# _Server
# ---------------------------------------------------------------------------

class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


# ---------------------------------------------------------------------------
# SetupServer
# ---------------------------------------------------------------------------

class SetupServer:
    """브라우저 기반 첫 실행 설정 서버.

    validator(provider, key) → (ok, msg) — 비동기, 기본값은 validate.validate.
    store_save(provider, key) — 동기, 기본값은 save_setup + save_key.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 0,
        validator: Callable | None = None,
        store_save: Callable | None = None,
    ) -> None:
        self._host = host
        self.port = port
        self._validator = validator or _default_validate
        self._store_save = store_save or _default_store_save
        self.done = threading.Event()
        self.chosen: str | None = None
        self._httpd: _Server | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://{self._host}:{self.port}/"

    def start(self) -> None:
        outer = self

        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:  # noqa: D102 - stderr 스팸 방지
                pass

            def _send_json(self, code: int, payload: dict) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                path = self.path.split("?", 1)[0]
                if path in ("/", "/index.html"):
                    body = SETUP_HTML.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_error(404)

            def do_POST(self) -> None:  # noqa: N802
                if self.path != "/setup":
                    self.send_error(404)
                    return
                try:
                    n = int(self.headers.get("Content-Length", "0"))
                    data = json.loads(self.rfile.read(n) or b"{}")
                    provider = str(data.get("provider", "")).strip()
                    key = str(data.get("key", "")).strip()
                except Exception:  # noqa: BLE001
                    self._send_json(400, {"ok": False, "error": "잘못된 요청입니다."})
                    return

                if not provider:
                    self._send_json(400, {"ok": False, "error": "프로바이더를 선택하세요."})
                    return

                try:
                    ok, msg = asyncio.run(outer._validator(provider, key))
                except Exception:  # noqa: BLE001
                    self._send_json(500, {"ok": False, "error": "검증 중 오류가 났습니다."})
                    return

                if ok:
                    try:
                        outer._store_save(provider, key)
                    except Exception:  # noqa: BLE001
                        self._send_json(500, {"ok": False, "error": "설정 저장 중 오류가 났습니다."})
                        return
                    outer.chosen = provider
                    outer.done.set()
                    self._send_json(200, {"ok": True, "message": msg})
                else:
                    self._send_json(200, {"ok": False, "error": msg})

        self._httpd = _Server((self._host, self.port), _Handler)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="jarvis-setup", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None


# ---------------------------------------------------------------------------
# 기본 store_save 구현
# ---------------------------------------------------------------------------

def _default_store_save(provider: str, key: str) -> None:
    save_setup(provider)
    if key:
        save_key(provider, key)
