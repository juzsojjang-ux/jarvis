# 아이폰 원격 명령 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 아이폰 단축어가 `POST /ask`(Bearer 토큰)로 텍스트를 보내면 실행 중인 자비스 두뇌가 답해 한국어 텍스트로 돌려준다 — 맥에서 소리내지 않고, 파괴적 도구는 원격에서 원천 차단.

**Architecture:** stdlib 스레드 HTTP 서버(`RemoteServer`, orb_server 패턴 — 핸들러 주입식이라 asyncio를 모름) + `Orchestrator.remote_turn`(THINKING 상태로 웨이크 차단, `_remote_busy`로 PTT 차단, `brain.remote_mode`로 파괴 도구 거부) + `__main__`의 `run_coroutine_threadsafe` 브리지.

**Tech Stack:** Python 3.11(.venv), stdlib http.server/secrets/hmac, pytest(+urllib로 실서버 인프로세스 테스트).

**Spec:** `docs/superpowers/specs/2026-06-11-iphone-remote-design.md`

**공통 규칙:** 작업 디렉터리 `/Users/2seongjae/jarvis`, 테스트 `.venv/bin/python -m pytest`. 테스트 서버는 반드시 `127.0.0.1` + 포트 0(자동 할당)으로 바인드 — `0.0.0.0` 금지. 실제 SDK·마이크·TTS 호출 금지.

---

### Task 1: 토큰 모듈

**Files:**
- Create: `jarvis/remote/__init__.py` (빈 파일)
- Create: `jarvis/remote/token.py`
- Test: `tests/remote/__init__.py` (빈 파일), `tests/remote/test_token.py`

- [ ] **Step 1: Write the failing tests** — `tests/remote/test_token.py`:

```python
from jarvis.remote.token import load_or_create_token


def test_creates_token_with_0600(tmp_path):
    p = tmp_path / "remote_token"
    tok = load_or_create_token(p)
    assert len(tok) >= 32
    assert p.read_text().strip() == tok
    assert (p.stat().st_mode & 0o777) == 0o600


def test_reuses_existing_token(tmp_path):
    p = tmp_path / "remote_token"
    first = load_or_create_token(p)
    assert load_or_create_token(p) == first


def test_regenerates_empty_file(tmp_path):
    p = tmp_path / "remote_token"
    p.write_text("  \n")
    tok = load_or_create_token(p)
    assert tok.strip()
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/remote/ -v` — FAIL(ModuleNotFoundError).

- [ ] **Step 3: Implement** — `jarvis/remote/token.py`:

```python
"""원격 명령 토큰 — 아이폰 단축어가 Authorization: Bearer 헤더로 보낸다.
첫 부팅에 생성해 ~/.jarvis/remote_token(0600)에 둔다. 배너에는 경로만 안내
(토큰 원문을 stdout에 찍지 않는다)."""
from __future__ import annotations

import secrets
from pathlib import Path

DEFAULT_TOKEN_PATH = Path.home() / ".jarvis" / "remote_token"


def load_or_create_token(path: Path | None = None) -> str:
    p = Path(path) if path is not None else DEFAULT_TOKEN_PATH
    if p.exists():
        tok = p.read_text(encoding="utf-8").strip()
        if tok:
            return tok
    tok = secrets.token_urlsafe(32)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(tok + "\n", encoding="utf-8")
    p.chmod(0o600)
    return tok
```

- [ ] **Step 4: Run** 같은 명령 — 3 passed.
- [ ] **Step 5: Commit** `git add jarvis/remote tests/remote && git commit -m "feat(원격): 단축어 인증 토큰 — 생성·재사용·0600"`

---

### Task 2: RemoteServer

**Files:**
- Create: `jarvis/remote/server.py`
- Test: `tests/remote/test_server.py`

- [ ] **Step 1: Write the failing tests** — `tests/remote/test_server.py`:

```python
import json
import urllib.error
import urllib.request

import pytest

from jarvis.remote.server import RemoteServer

TOKEN = "test-token-123"


def _post(port, text="안녕", token=TOKEN, path="/ask"):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps({"text": text}).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


@pytest.fixture()
def server():
    calls = []

    def handler(text):
        calls.append(text)
        if text == "boom":
            raise RuntimeError("brain down")
        if text == "slow":
            raise TimeoutError()
        return {"reply": f"답: {text}", "reply_en": f"re: {text}"}

    srv = RemoteServer(handler, "127.0.0.1", 0, TOKEN)
    srv.start()
    yield srv, calls
    srv.stop()


def test_ok_roundtrip(server):
    srv, calls = server
    status, body = _post(srv.port)
    assert status == 200
    assert body["reply"] == "답: 안녕"
    assert calls == ["안녕"]


def test_rejects_bad_token(server):
    srv, calls = server
    with pytest.raises(urllib.error.HTTPError) as e:
        _post(srv.port, token="wrong")
    assert e.value.code == 401
    assert calls == []  # 핸들러까지 못 간다


def test_rejects_empty_text(server):
    srv, _calls = server
    with pytest.raises(urllib.error.HTTPError) as e:
        _post(srv.port, text="  ")
    assert e.value.code == 400


def test_handler_error_is_500(server):
    srv, _calls = server
    with pytest.raises(urllib.error.HTTPError) as e:
        _post(srv.port, text="boom")
    assert e.value.code == 500


def test_handler_timeout_is_504(server):
    srv, _calls = server
    with pytest.raises(urllib.error.HTTPError) as e:
        _post(srv.port, text="slow")
    assert e.value.code == 504


def test_unknown_path_404(server):
    srv, _calls = server
    with pytest.raises(urllib.error.HTTPError) as e:
        _post(srv.port, path="/other")
    assert e.value.code == 404
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/remote/test_server.py -v` — FAIL(ImportError).

- [ ] **Step 3: Implement** — `jarvis/remote/server.py`:

```python
"""아이폰 원격 명령 수신 — orb_server처럼 stdlib 스레드 HTTP(의존성 0).

핸들러는 주입된다: __main__이 asyncio 루프로 던지는 브리지를 넣는다(이 모듈은
asyncio를 모른다). 인증 실패는 본문 없는 401(정보 누설 금지). 어떤 실패도
부팅·음성 파이프라인을 깨지 않는다."""
from __future__ import annotations

import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class RemoteServer:
    def __init__(self, handler, host: str, port: int, token: str) -> None:
        self._handler = handler  # (text: str) -> dict — 스레드에서 블로킹 호출
        self._host = host
        self.port = port  # start() 후 실제 바인드 포트로 갱신(테스트는 0 사용)
        self._token = token
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://{self._host}:{self.port}/ask"

    def start(self) -> None:
        outer = self

        class _Handler(BaseHTTPRequestHandler):
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
                if self.path != "/ask":
                    self._send(404, {"reply": "없는 경로입니다."})
                    return
                auth = self.headers.get("Authorization", "")
                if not hmac.compare_digest(auth, f"Bearer {outer._token}"):
                    print("[원격] 인증 실패 요청 거부")
                    self._send(401)
                    return
                try:
                    n = int(self.headers.get("Content-Length", "0"))
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
```

- [ ] **Step 4: Run** 같은 명령 — 6 passed.
- [ ] **Step 5: Commit** `git add jarvis/remote/server.py tests/remote/test_server.py && git commit -m "feat(원격): RemoteServer — /ask 토큰 인증+핸들러 주입(stdlib 스레드)"`

---

### Task 3: Orchestrator.remote_turn

**Files:**
- Modify: `jarvis/core/orchestrator.py` — `__init__`에 `_remote_busy`, `_on_release` 가드, 새 메서드 `remote_turn`
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing tests** — `tests/test_orchestrator.py` 끝에 추가(기존 `_make()` 하니스, 가짜 두뇌가 텍스트를 yield하고 pb.feeds가 발화를 기록하는 구조를 그대로 사용; `_on_release` 가드 테스트는 기존 PTT 테스트(tests/test_ptt.py)의 capture 페이크 패턴을 따르되 여기 두면 됨):

```python
def test_remote_turn_collects_text_without_tts():
    orch, pb = _make()

    async def run():
        return await orch.remote_turn("안녕")
    res = asyncio.run(run())
    assert res["reply"]
    assert pb.feeds == []  # 원격 턴은 절대 말하지 않는다
    assert orch.state == State.IDLE


def test_remote_turn_busy_when_not_idle():
    orch, _pb = _make()
    orch.state = State.THINKING

    async def run():
        return await orch.remote_turn("안녕")
    res = asyncio.run(run())
    assert "다른 일" in res["reply"]


def test_remote_turn_sets_and_clears_remote_mode():
    orch, _pb = _make()
    seen = []

    class _FlagBrain:
        remote_mode = False
        last_subtitle = "한국어 답"

        async def respond(self, text):
            seen.append(self.remote_mode)
            yield "english answer"

    orch.brain = _FlagBrain()

    async def run():
        return await orch.remote_turn("hi")
    res = asyncio.run(run())
    assert seen == [True]                 # 응답 생성 중엔 원격 모드
    assert orch.brain.remote_mode is False  # 끝나면 해제
    assert res["reply"] == "한국어 답"
    assert res["reply_en"] == "english answer"


def test_remote_turn_recovers_on_brain_error():
    orch, _pb = _make()

    class _BoomBrain:
        async def respond(self, text):
            raise RuntimeError("down")
            yield

    orch.brain = _BoomBrain()

    async def run():
        return await orch.remote_turn("hi")
    res = asyncio.run(run())
    assert "오류" in res["reply"]
    assert orch.state == State.IDLE


def test_remote_turn_blocks_concurrent_remote():
    orch, _pb = _make()
    orch._remote_busy = True
    orch.state = State.IDLE

    async def run():
        return await orch.remote_turn("hi")
    res = asyncio.run(run())
    assert "다른 일" in res["reply"]
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_orchestrator.py -k remote -v` — FAIL(AttributeError).

- [ ] **Step 3: Implement** — `jarvis/core/orchestrator.py`:

(a) `__init__`에 `self._remote_busy = False` 추가(`self._warm_task` 옆).

(b) `_on_release`에서 `self.state = State.TRANSCRIBING` 직전에 가드 삽입:

```python
        if self._remote_busy:
            self._to_idle()  # 원격 턴 진행 중 — PTT 발화 폐기(두뇌 동시 사용 방지)
            return
```

(c) `announce` 메서드 근처(능동 알림 섹션 뒤)에 추가:

```python
    # ----- 아이폰 원격 명령 -----
    async def remote_turn(self, text: str) -> dict:
        """원격(HTTP) 텍스트 턴 — TTS 없이 텍스트로만 답한다(사용자 부재).
        THINKING 상태가 웨이크 게이트를 막고 _remote_busy가 PTT 경로를 막아
        두뇌 동시 사용(응답 훔치기 레이스)을 차단한다."""
        if not text.strip():
            return {"reply": "무엇을 도와드릴까요?"}
        if self._remote_busy or not self._can_announce():
            return {"reply": "지금 다른 일을 처리하고 있습니다. 잠시 후 다시 시도해 주세요."}
        self._remote_busy = True
        self.state = State.THINKING
        self._publish("thinking")
        if hasattr(self.brain, "remote_mode"):
            self.brain.remote_mode = True
        try:
            parts: list[str] = []
            async for delta in self.brain.respond(text):
                parts.append(delta)
            en = "".join(parts).strip()
            ko = (getattr(self.brain, "last_subtitle", "") or "").strip()
            return {"reply": ko or en or "답을 만들지 못했습니다.", "reply_en": en}
        except Exception as exc:  # noqa: BLE001 - 원격 한 턴 실패가 상태를 가두면 안 된다
            print(f"[원격] 처리 오류: {exc}")
            return {"reply": "처리 중 오류가 났습니다."}
        finally:
            if hasattr(self.brain, "remote_mode"):
                self.brain.remote_mode = False
            self._remote_busy = False
            self._to_idle()
```

- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/test_orchestrator.py tests/test_ptt.py -v` — all passed.
- [ ] **Step 5: Commit** `git add jarvis/core/orchestrator.py tests/test_orchestrator.py && git commit -m "feat(원격): remote_turn — TTS 없는 텍스트 턴+음성 경로 상호 배제"`

---

### Task 4: 원격 모드 파괴 도구 차단

**Files:**
- Modify: `jarvis/brain/subscription.py` — `__init__`에 `remote_mode`, `_can_use_tool`에 거부 분기
- Test: `tests/brain/test_subscription.py`

- [ ] **Step 1: Write the failing test**:

```python
def test_can_use_tool_remote_mode_denies_without_confirm():
    import asyncio

    from jarvis.brain.subscription import SubscriptionBrain
    from jarvis.core.config import Settings

    confirm_calls = []

    async def confirm(prompt):
        confirm_calls.append(prompt)
        return True  # 승인해 주더라도 원격이면 도달조차 하면 안 된다

    brain = SubscriptionBrain(Settings(), None, "p" * 4096, confirm=confirm)
    brain.remote_mode = True

    async def run():
        deny = await brain._can_use_tool("Bash", {"command": "rm -rf /"}, None)
        read = await brain._can_use_tool("Read", {}, None)
        jarvis_tool = await brain._can_use_tool("mcp__jarvis__get_time", {}, None)
        return deny, read, jarvis_tool

    deny, read, jarvis_tool = asyncio.run(run())
    assert type(deny).__name__ == "PermissionResultDeny"
    assert "원격" in deny.message
    assert confirm_calls == []  # 음성 확인을 부르지도 않는다
    assert type(read).__name__ == "PermissionResultAllow"
    assert type(jarvis_tool).__name__ == "PermissionResultAllow"
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/brain/test_subscription.py -k remote -v` — FAIL.

- [ ] **Step 3: Implement** — `jarvis/brain/subscription.py`:

(a) `__init__`에 (`self._xlate_locks` 줄 다음):
```python
        self.remote_mode = False  # 원격 턴 중 — 파괴 도구는 음성 확인 없이 즉시 거부
```

(b) `_can_use_tool`에서 `base = tool_name.split("__")[-1]` 줄 바로 다음에:
```python
        if self.remote_mode:
            # 원격엔 음성 확인 채널이 없다 — 확인을 시도하지 말고 차단.
            return PermissionResultDeny(message=f"{base}은 원격에서는 실행할 수 없습니다.")
```

- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/brain/ -v` — all passed.
- [ ] **Step 5: Commit** `git add jarvis/brain/subscription.py tests/brain/test_subscription.py && git commit -m "feat(원격): remote_mode면 파괴 도구 확인 없이 거부 — 원격 음성확인 부재 차단"`

---

### Task 5: 설정 + 부팅 배선

**Files:**
- Modify: `jarvis/core/config.py` — M6 블록 다음에 M7
- Modify: `jarvis/__main__.py` — RemoteServer 시작/종료
- Test: `tests/core/test_config_m2.py`

- [ ] **Step 1: Write the failing test** — `tests/core/test_config_m2.py` 끝에:

```python
def test_remote_defaults():
    s = Settings()
    assert s.remote_enabled is True
    assert s.remote_host == "0.0.0.0"
    assert s.remote_port == 8790
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/core/test_config_m2.py -v` — FAIL.

- [ ] **Step 3: Implement**

(a) `jarvis/core/config.py` — `screen_control_ttl_s` 줄 다음에:

```python

    # --- M7 아이폰 원격 명령 ---
    remote_enabled: bool = True
    remote_host: str = "0.0.0.0"   # LAN 수신(외부망은 Tailscale 권장 — 포트포워딩 비권장)
    remote_port: int = 8790
```

(b) `jarvis/__main__.py`:
- import 블록에 추가: `from .remote.server import RemoteServer` / `from .remote.token import load_or_create_token`
- HUD 블록(try/except OSError 끝)과 "자비스 준비 완료" print 사이에:

```python
        remote = None
        if orch.settings.remote_enabled:
            try:
                loop = asyncio.get_running_loop()

                def _remote_bridge(text: str) -> dict:
                    fut = asyncio.run_coroutine_threadsafe(orch.remote_turn(text), loop)
                    return fut.result(timeout=120.0)

                remote = RemoteServer(_remote_bridge, orch.settings.remote_host,
                                      orch.settings.remote_port, load_or_create_token())
                remote.start()
                print(f"[원격] 아이폰 단축어 수신: {remote.url} "
                      "(토큰: ~/.jarvis/remote_token · 설정법: docs/REMOTE.md)")
            except OSError as exc:  # 포트 사용 중 등 — 원격은 옵션, 부팅은 계속
                print(f"[원격] 시작 실패(비활성화): {exc}")
```

- 마지막 `finally:` 블록(overlay terminate)에 추가:

```python
            if remote is not None:
                remote.stop()
```

- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/core/test_config_m2.py tests/test_main_wiring.py -v && .venv/bin/python -c "import jarvis.__main__"` — all passed + import OK.
- [ ] **Step 5: Commit** `git add jarvis/core/config.py jarvis/__main__.py tests/core/test_config_m2.py && git commit -m "feat(원격): M7 설정+부팅 배선 — asyncio 브리지로 RemoteServer 기동"`

---

### Task 6: 단축어 가이드 문서 + 전체 검증

**Files:**
- Create: `docs/REMOTE.md`

- [ ] **Step 1: Write** `docs/REMOTE.md`:

```markdown
# 아이폰에서 자비스 부르기 (단축어 설정)

## 준비물
- 맥과 아이폰이 같은 와이파이 (밖에서도 쓰려면 둘 다 Tailscale 설치 — 포트포워딩은 비권장)
- 맥 주소: 시스템 설정→네트워크의 IP(예: 192.168.0.10) 또는 Tailscale 주소
- 토큰: 맥에서 `cat ~/.jarvis/remote_token`

## 단축어 만들기 (아이폰 단축어 앱)
1. 새 단축어, 이름 "자비스"
2. 동작 ① **"입력 요청"** — 질문: "무엇을 도와드릴까요?", 입력 유형: 텍스트
   (Siri로 실행하면 받아쓰기로 동작)
3. 동작 ② **"URL 내용 가져오기"**
   - URL: `http://<맥주소>:8790/ask`
   - 방법: POST · 요청 본문: JSON · `text` = ①의 제공된 입력
   - 헤더: `Authorization` = `Bearer <토큰>`
4. 동작 ③ **"사전 값 가져오기"** — ②의 결과에서 `reply`
5. 동작 ④ **"텍스트 말하기"**(또는 "결과 보기") — ③의 값
6. "자비스야 시리야" 식으로: Siri에게 "자비스 실행해"라고 말하면 ①이 받아쓰기로 뜬다

## 동작 규칙
- 자비스가 맥에서 음성 대화 중이면 "지금 다른 일을 처리하고 있습니다"라고 답한다
- 원격에서는 파일 수정·명령 실행 같은 파괴적 작업이 자동 거부된다(보안)
- 응답 한도 120초

## 문제 해결
- 401: 토큰 불일치 — 헤더 `Bearer ` 접두사와 토큰 재확인
- 연결 안 됨: 같은 네트워크인지, 맥 방화벽에서 Python 수신 허용했는지 확인
```

- [ ] **Step 2: 전체 검증**

Run: `.venv/bin/python -m pytest` — 전부 통과(386+신규 ~15).
Run: `.venv/bin/python -c "import jarvis.__main__; print('OK')"`

- [ ] **Step 3: Commit** `git add docs/REMOTE.md && git commit -m "docs(원격): 아이폰 단축어 설정 가이드"`

- [ ] **Step 4: 라이브** — 자비스 재시작 후 맥에서 자체 왕복:
`curl -s -X POST http://127.0.0.1:8790/ask -H "Authorization: Bearer $(cat ~/.jarvis/remote_token)" -H 'Content-Type: application/json' -d '{"text":"지금 몇 시야?"}'`
→ 한국어 시간 답 JSON. 이후 아이폰 단축어로 같은 와이파이 테스트(사용자).
