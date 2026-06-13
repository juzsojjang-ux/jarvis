# HUD 작업실 패널 재설계 + 오브 알파 — 구현 플랜

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** macOS WebKit에서 오브 검정 박스를 알파 영상으로 제거하고, 우상단 단일 패널을 오브 중심 방사형 "작업실" 패널 시스템(코너↔중앙 두 모드, 두뇌 패널 + 실시간 텔레메트리, 영화 디자인 언어)으로 교체한다.

**Architecture:** 오브는 알파가 박힌 영상(mac=HEVC .mov / win=VP9 .webm)을 엔진별로 골라 재생(SVG 필터 폐기). 패널은 SSE 페이로드에 새 `panels[]` 배열을 실어 보내고, OrbHub가 두뇌 알림(notice)과 텔레메트리 공급자가 보낸 항목을 합쳐 emit한다. orb.html이 `panels`를 모드별 슬롯에 렌더한다. 기존 `notice` 필드는 하위호환 유지.

**Tech Stack:** Python stdlib(http.server + threads), 순수 JS/CSS/SVG(orb.html), ffmpeg(자산은 이미 구움), PyInstaller(jarvis.spec), pytest.

**참고 문서:** 스펙 `docs/superpowers/specs/2026-06-14-hud-panel-workshop-redesign-design.md`, 레퍼런스 `docs/superpowers/specs/jarvis-hud-movie-references.md`.

**선행 상태(이미 완료):** `jarvis/hud/assets/orb-alpha.mov`(HEVC+alpha, ~17MB)와 `jarvis/hud/assets/orb-alpha.webm`(VP9+alpha, ~22MB)는 이미 구워져 있음(코너 alpha=0·중앙 불투명 검증 완료). `orb.mp4`(원본)도 아직 존재.

---

## 파일 구조 (이 플랜이 만지는 것)

- `jarvis/hud/orb_server.py` — 수정: 알파 자산 라우트(`/assets/orb-alpha.mov`·`.webm`), 자산 경로 헬퍼 일반화, OrbHub에 `panels`/`_telemetry`/`publish_telemetry` 추가.
- `jarvis/hud/telemetry.py` — 신규: 순수 `collect()` + `TelemetryProvider`(주기 push 스레드).
- `jarvis/hud/orb.html` — 수정: 알파 영상 교체·SVG 필터 제거, 단일 `#notice`→동적 패널 렌더러(두 모드·유동·영화 언어).
- `jarvis/core/orchestrator.py` — 수정: TelemetryProvider 기동/종료 + 상태 공급(mic/작업수).
- `jarvis/tools/jarvis_mcp.py` — 수정: `show_panel` 설명에 카드 구분자(`---`) 안내(B 멀티카드, 새 인자 없이).
- `packaging/jarvis.spec` — 수정: `orb.mp4` 번들 → `orb-alpha.mov`/`.webm`.
- `tests/hud/test_orb_server.py` — 수정: 기존 emit 비교에 `panels` 키 반영 + 새 테스트.
- `tests/hud/test_telemetry.py` — 신규: `collect()` 단위 테스트.

---

## Task 1: OrbHub `panels` 모델 + 텔레메트리 채널

**Files:**
- Modify: `jarvis/hud/orb_server.py` (OrbHub: `__init__`, `_emit`, 새 `publish_telemetry`, 새 모듈함수 `_brain_cards`)
- Test: `tests/hud/test_orb_server.py`

- [ ] **Step 1: 실패 테스트 작성** — `tests/hud/test_orb_server.py` 끝에 추가:

```python
# ---- panels 모델 -----------------------------------------------------------
def test_emit_includes_panels_key_default_empty():
    hub = OrbHub()
    evt = hub.publish("idle", 0.0)
    assert evt["panels"] == []

def test_notice_becomes_single_brain_card():
    hub = OrbHub()
    evt = hub.publish_notice("검색 결과\n- 항목1\n- 항목2")
    assert len(evt["panels"]) == 1
    p = evt["panels"][0]
    assert p["kind"] == "brain" and p["title"] == "검색 결과"
    assert "항목1" in p["body"]
    assert evt["notice"] == "검색 결과\n- 항목1\n- 항목2"  # 하위호환 유지

def test_notice_splits_into_cards_on_separator():
    hub = OrbHub()
    evt = hub.publish_notice("일정\n3시 회의\n---\n검색\n뉴스 5건")
    titles = [p["title"] for p in evt["panels"] if p["kind"] == "brain"]
    assert titles == ["일정", "검색"]

def test_publish_telemetry_merges_with_brain():
    hub = OrbHub()
    hub.publish_notice("메인\n본문")
    evt = hub.publish_telemetry([
        {"id": "clock", "title": "14:32", "body": "", "kind": "telemetry", "tone": "cyan"},
    ])
    kinds = [p["kind"] for p in evt["panels"]]
    assert kinds.count("brain") == 1 and kinds.count("telemetry") == 1

def test_telemetry_replaced_not_appended():
    hub = OrbHub()
    hub.publish_telemetry([{"id": "a", "title": "A", "body": "", "kind": "telemetry", "tone": "cyan"}])
    evt = hub.publish_telemetry([{"id": "b", "title": "B", "body": "", "kind": "telemetry", "tone": "cyan"}])
    tel = [p for p in evt["panels"] if p["kind"] == "telemetry"]
    assert len(tel) == 1 and tel[0]["id"] == "b"
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/hud/test_orb_server.py -k "panels or telemetry or card" -q`
Expected: FAIL (`KeyError: 'panels'` / `publish_telemetry` 없음)

- [ ] **Step 3: 구현** — `jarvis/hud/orb_server.py`

`OrbHub.__init__`의 상태 줄을 교체:

```python
        self._notice = ""  # 우측 정보(두뇌 show_panel) — 명시적으로 비울 때까지 유지
        self._telemetry: list[dict] = []  # 자비스 실시간 텔레메트리 패널(주기 갱신)
        self._expand = False  # A↔B 전환 상태(sticky)
        self._last = {"state": "idle", "level": 0.0, "text": "", "notice": "",
                      "expand": False, "panels": []}
```

모듈 레벨(클래스 위)에 카드 분해 헬퍼 추가:

```python
def _brain_cards(notice: str) -> list[dict]:
    """두뇌 알림 텍스트를 패널 카드로 분해. '---' 줄로 여러 카드, 각 카드의 첫 줄=제목.
    경고(⚠/오류)는 tone=warn. 빈 문자열이면 카드 없음."""
    notice = (notice or "").strip()
    if not notice:
        return []
    cards = []
    for chunk in notice.split("\n---\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        lines = chunk.split("\n", 1)
        title = lines[0].strip()
        body = lines[1].strip() if len(lines) > 1 else ""
        warn = ("⚠" in chunk) or ("오류" in chunk)
        cards.append({"id": f"brain{len(cards)}", "title": title, "body": body,
                      "kind": "brain", "tone": "warn" if warn else "cyan"})
    return cards
```

`publish_notice` 아래에 추가:

```python
    def publish_telemetry(self, items: list[dict] | None) -> dict:
        """자비스 텔레메트리 패널 목록을 통째로 교체(주기 호출). 상태/자막/알림은 유지."""
        self._telemetry = list(items or [])
        last = self._last
        return self._emit(last.get("state", "idle"), last.get("level", 0.0))
```

`_emit`를 교체(panels 합성 추가):

```python
    def _emit(self, state: str, level: float) -> dict:
        panels = _brain_cards(self._notice) + list(self._telemetry)
        evt = {"state": state, "level": round(max(0.0, min(1.0, float(level))), 4),
               "text": self._text, "notice": self._notice, "expand": self._expand,
               "panels": panels}
        self._last = evt
        with self._lock:
            clients = list(self._clients)
        for q in clients:
            try:
                q.put_nowait(dict(evt))
            except queue.Full:
                pass
        return evt
```

- [ ] **Step 4: 기존 테스트 갱신** — 기존 3개 비교 dict에 `"panels": []` 추가. `tests/hud/test_orb_server.py`에서:

```python
    assert q.get_nowait() == {"state": "thinking", "level": 0.4, "text": "", "notice": "", "expand": False, "panels": []}
```
```python
    assert q.get_nowait() == {"state": "speaking", "level": 0.7, "text": "안녕하세요", "notice": "", "expand": False, "panels": []}
```
(세 번째 자막 테스트는 `["text"]`만 보므로 변경 불필요.)

- [ ] **Step 5: 통과 확인**

Run: `pytest tests/hud/test_orb_server.py -q`
Expected: PASS (전부)

- [ ] **Step 6: 커밋**

```bash
git add jarvis/hud/orb_server.py tests/hud/test_orb_server.py
git commit -m "feat(hud): SSE에 panels[] 배열 신설(두뇌 카드+텔레메트리 병합), notice 하위호환"
```

---

## Task 2: 텔레메트리 수집기 + 공급자

**Files:**
- Create: `jarvis/hud/telemetry.py`
- Test: `tests/hud/test_telemetry.py`

- [ ] **Step 1: 실패 테스트 작성** — `tests/hud/test_telemetry.py`:

```python
from jarvis.hud.telemetry import collect


def test_collect_clock_always_present():
    items = collect(clock="14:32", mic_on=False, task_count=0)
    ids = [i["id"] for i in items]
    assert "clock" in ids
    clock = next(i for i in items if i["id"] == "clock")
    assert clock["kind"] == "telemetry" and "14:32" in clock["title"]


def test_collect_mic_reflects_state():
    on = next(i for i in collect(clock="0", mic_on=True, task_count=0) if i["id"] == "mic")
    off = next(i for i in collect(clock="0", mic_on=False, task_count=0) if i["id"] == "mic")
    assert "●" in on["body"] or "LIVE" in on["body"]
    assert on["body"] != off["body"]


def test_collect_tasks_hidden_when_zero():
    ids = [i["id"] for i in collect(clock="0", mic_on=False, task_count=0)]
    assert "tasks" not in ids
    ids2 = [i["id"] for i in collect(clock="0", mic_on=False, task_count=3)]
    assert "tasks" in ids2


def test_collect_omits_cpu_when_none():
    ids = [i["id"] for i in collect(clock="0", mic_on=False, task_count=0, cpu=None, mem=None)]
    assert "sys" not in ids
    ids2 = [i["id"] for i in collect(clock="0", mic_on=False, task_count=0, cpu=12, mem=41)]
    assert "sys" in ids2


def test_collect_net_optional():
    ids = [i["id"] for i in collect(clock="0", mic_on=False, task_count=0, net=None)]
    assert "net" not in ids
    ids2 = [i["id"] for i in collect(clock="0", mic_on=False, task_count=0, net=True)]
    assert "net" in ids2
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/hud/test_telemetry.py -q`
Expected: FAIL (`ModuleNotFoundError: jarvis.hud.telemetry`)

- [ ] **Step 3: 구현** — `jarvis/hud/telemetry.py`:

```python
"""HUD 실시간 텔레메트리 — 진짜 데이터만(가짜 장식 금지). 순수 collect()는 입력→패널 dict
리스트로 단위 테스트가 쉽고, TelemetryProvider가 주기적으로 샘플링해 OrbHub에 push한다."""
from __future__ import annotations

import threading
from collections.abc import Callable


def collect(*, clock: str, mic_on: bool, task_count: int,
            cpu: int | None = None, mem: int | None = None,
            net: bool | None = None) -> list[dict]:
    """텔레메트리 패널 목록. 데이터 없는 항목은 생략(Kent Seki '기능 없으면 뺀다')."""
    items: list[dict] = [
        {"id": "clock", "title": f"◷ {clock}", "body": "", "kind": "telemetry", "tone": "cyan"},
        {"id": "mic", "title": "◇ 입력", "kind": "telemetry", "tone": "cyan",
         "body": "MIC ● LIVE" if mic_on else "MIC ○ 대기"},
    ]
    if net is not None:
        items.append({"id": "net", "title": "◇ NET", "kind": "telemetry", "tone": "cyan",
                      "body": "TAILSCALE ✓" if net else "OFFLINE ✕"})
    if cpu is not None and mem is not None:
        items.append({"id": "sys", "title": "◰ SYS LOAD", "kind": "telemetry", "tone": "gold",
                      "body": f"CPU {cpu}% · MEM {mem}%",
                      "gauge": {"cpu": int(cpu), "mem": int(mem)}})
    if task_count > 0:
        items.append({"id": "tasks", "title": "◳ 작업", "kind": "telemetry", "tone": "gold",
                      "body": f"백그라운드 {task_count}건"})
    return items


def _sample_cpu_mem() -> tuple[int | None, int | None]:
    """psutil 있으면 CPU/MEM(%) 정수, 없으면 (None, None)."""
    try:
        import psutil  # 선택 의존성 — 없으면 게이지 생략
    except Exception:
        return (None, None)
    try:
        return (int(psutil.cpu_percent(interval=None)), int(psutil.virtual_memory().percent))
    except Exception:
        return (None, None)


class TelemetryProvider:
    """주기적으로 텔레메트리를 수집해 hub.publish_telemetry로 push하는 데몬 스레드.
    state_fn()은 오케스트레이터가 제공: {'mic_on': bool, 'task_count': int} 반환."""

    def __init__(self, hub, state_fn: Callable[[], dict], interval: float = 2.0,
                 clock_fn: Callable[[], str] | None = None) -> None:
        self._hub = hub
        self._state_fn = state_fn
        self._interval = interval
        self._clock_fn = clock_fn or (lambda: __import__("time").strftime("%H:%M"))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                st = self._state_fn() or {}
                cpu, mem = _sample_cpu_mem()
                items = collect(clock=self._clock_fn(), mic_on=bool(st.get("mic_on")),
                                task_count=int(st.get("task_count", 0)), cpu=cpu, mem=mem,
                                net=st.get("net"))
                self._hub.publish_telemetry(items)
            except Exception:  # 텔레메트리가 HUD/음성을 깨면 안 된다
                pass
            self._stop.wait(self._interval)

    def stop(self) -> None:
        self._stop.set()
        self._thread = None
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/hud/test_telemetry.py -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add jarvis/hud/telemetry.py tests/hud/test_telemetry.py
git commit -m "feat(hud): 실시간 텔레메트리 수집기 collect() + TelemetryProvider(주기 push)"
```

---

## Task 3: 오케스트레이터에 텔레메트리 공급자 연결

**Files:**
- Modify: `jarvis/core/orchestrator.py` (`__init__` 부근에서 provider 생성/기동, 종료 훅, 상태 함수)
- Test: `tests/hud/test_telemetry.py` (state_fn 계약용 경량 테스트 추가)

- [ ] **Step 1: 상태 함수 테스트 추가** — `tests/hud/test_telemetry.py`에:

```python
def test_provider_pushes_to_hub():
    from jarvis.hud.orb_server import OrbHub
    from jarvis.hud.telemetry import TelemetryProvider
    hub = OrbHub()
    prov = TelemetryProvider(hub, state_fn=lambda: {"mic_on": True, "task_count": 2},
                             interval=0.05, clock_fn=lambda: "09:00")
    prov.start()
    import time; time.sleep(0.15); prov.stop()
    evt = hub.publish("idle", 0.0)
    ids = [p["id"] for p in evt["panels"] if p["kind"] == "telemetry"]
    assert "clock" in ids and "mic" in ids and "tasks" in ids
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/hud/test_telemetry.py::test_provider_pushes_to_hub -q`
Expected: PASS (이 테스트는 provider만 검증하므로 바로 통과해야 함 — 통과하면 OK, Step 3로)

- [ ] **Step 3: 구현** — `jarvis/core/orchestrator.py`

상단 import 부근(`from ..hud import notice_bus` 근처)에 추가:

```python
from ..hud.telemetry import TelemetryProvider
```

`__init__`에서 `notice_bus.set_sink(self._panel_sink)` 줄(78행 부근) 바로 아래에 추가:

```python
        # HUD 텔레메트리 공급자 — hub가 있을 때만(테스트/HUD 비활성 시 생략)
        self._telemetry = None
        hub = getattr(self.hud, "hub", None)
        if hub is not None:
            self._telemetry = TelemetryProvider(hub, state_fn=self._telemetry_state)
            self._telemetry.start()
```

`_panel_sink` 메서드 아래에 상태 함수 추가:

```python
    def _telemetry_state(self) -> dict:
        """텔레메트리 공급자에 넘길 실시간 상태(진짜 데이터). 예외는 공급자가 삼킨다."""
        return {
            "mic_on": self.state in (State.CAPTURING, State.LISTENING)
                      if hasattr(State, "LISTENING") else self.state == State.CAPTURING,
            "task_count": len(self._bg_tasks),
            "net": None,  # 네트워크 표시는 후속(현재는 생략 — 가짜 데이터 금지)
        }
```

종료 경로(`stop`/`shutdown`/`close` 중 존재하는 것 — `OrbServer.stop()`을 부르는 곳)에서 provider 정지. 해당 메서드 본문 시작에 추가:

```python
        if getattr(self, "_telemetry", None) is not None:
            self._telemetry.stop()
```

> 주: 오케스트레이터 종료 메서드명이 다르면(예: `aclose`), `self.hud.stop()` 또는 `OrbServer` 정지를 호출하는 지점을 찾아 같은 위치에 넣는다.

- [ ] **Step 4: 회귀 확인**

Run: `pytest tests/ -q -k "orchestrator or telemetry or orb"`
Expected: PASS (기존 오케스트레이터 테스트 깨지지 않음)

- [ ] **Step 5: 커밋**

```bash
git add jarvis/core/orchestrator.py tests/hud/test_telemetry.py
git commit -m "feat(hud): 오케스트레이터가 텔레메트리 공급자 기동(마이크/작업수 실시간 주입)"
```

---

## Task 4: 알파 영상 — 서버 라우트 + 자산 경로

**Files:**
- Modify: `jarvis/hud/orb_server.py` (`_orb_asset_path`→`_orb_asset(name)`, do_GET 라우트, content-type 매핑)
- Test: `tests/hud/test_orb_server.py`

- [ ] **Step 1: 실패 테스트 작성** — `tests/hud/test_orb_server.py`에:

```python
# ---- 알파 영상 자산 ---------------------------------------------------------
def test_alpha_assets_served(tmp_path):
    import urllib.request
    srv = OrbServer(port=0)
    srv.start()
    try:
        base = srv.url
        for name, ctype in [("orb-alpha.webm", "video/webm"), ("orb-alpha.mov", "video/quicktime")]:
            with urllib.request.urlopen(base + "assets/" + name, timeout=3) as r:
                assert r.status == 200
                assert r.headers["Content-Type"] == ctype
    finally:
        srv.stop()
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/hud/test_orb_server.py::test_alpha_assets_served -q`
Expected: FAIL (404 — 라우트 없음)

- [ ] **Step 3: 구현** — `jarvis/hud/orb_server.py`

`_orb_asset_path`를 다음으로 교체:

```python
_ASSET_CTYPE = {".mov": "video/quicktime", ".webm": "video/webm", ".mp4": "video/mp4"}


def _orb_asset(name: str) -> Path:
    """번들(frozen) 우선, 없으면 개발 경로의 hud/assets/<name>."""
    safe = Path(name).name  # 경로 탈출 방지
    mp = getattr(sys, "_MEIPASS", None)
    if mp:
        p = Path(mp) / "jarvis" / "hud" / "assets" / safe
        if p.exists():
            return p
    return Path(__file__).resolve().parent / "assets" / safe
```

do_GET의 `elif path == "/assets/orb.mp4":` 블록을 교체:

```python
            elif path.startswith("/assets/") and path.rsplit(".", 1)[-1] in ("mov", "webm", "mp4"):
                name = path[len("/assets/"):]
                try:
                    data = _orb_asset(name).read_bytes()
                except Exception:
                    self.send_error(404)
                    return
                ctype = _ASSET_CTYPE.get(Path(name).suffix, "application/octet-stream")
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "max-age=86400")
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/hud/test_orb_server.py -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add jarvis/hud/orb_server.py tests/hud/test_orb_server.py
git commit -m "feat(hud): 알파 영상 자산 라우트(.mov video/quicktime, .webm video/webm)"
```

---

## Task 5: orb.html — 알파 영상 교체 + SVG 필터 제거

**Files:**
- Modify: `jarvis/hud/orb.html` (video 요소, `#lumakey` SVG/filter 제거, 엔진 분기 JS)

- [ ] **Step 1: 영상 요소 교체** — `<div id="orbwrap">` 내부의 `<video ...>`를 교체:

```html
  <div id="orbwrap">
    <div id="orbglow"></div>
    <video id="orbvid" autoplay loop muted playsinline></video>
    <div id="orbcore"></div>
  </div>
```

- [ ] **Step 2: SVG lumakey 필터 블록 제거** — `<svg ... id="lumakey" ...> ... </svg>` 전체 삭제.

- [ ] **Step 3: `#orbvid` 필터에서 lumakey 제거** — CSS의

```css
  #orbvid{width:100%;height:100%;object-fit:contain;
    transform:scale(var(--orbscale,1));
    filter:brightness(var(--orbbright,1)) url(#lumakey)}
```
를 (url 제거):
```css
  #orbvid{width:100%;height:100%;object-fit:contain;
    transform:scale(var(--orbscale,1));
    filter:brightness(var(--orbbright,1))}
```

- [ ] **Step 4: 엔진별 소스 선택 JS 추가** — `<script>` 상단(`const cv = ...` 앞)에:

```javascript
// 알파 영상: WebKit(WKWebView)은 HEVC-alpha .mov, Chromium(WebView2)은 VP9-alpha .webm.
// (WebKit은 .webm 알파 미지원, Chromium은 .mov HEVC-alpha 미지원 — UA로 확정 분기.)
(function(){
  var v = document.getElementById("orbvid");
  var ua = navigator.userAgent;
  var isWebKit = /AppleWebKit/.test(ua) && !/Chrome|Chromium|Edg|CriOS/.test(ua);
  v.src = isWebKit ? "/assets/orb-alpha.mov" : "/assets/orb-alpha.webm";
  v.play && v.play().catch(function(){});
})();
```

- [ ] **Step 5: 수동 검증(Chromium)** — 정적 서버로 webm 알파 확인:

```bash
cd /Users/2seongjae/jarvis/jarvis/hud && (nohup python3 -m http.server 8799 >/tmp/hud_static.log 2>&1 &) ; sleep 1
```
Chrome DevTools MCP로 `http://127.0.0.1:8799/orb.html` 열고, body 배경을 임시 어둡게 한 뒤 오브가 **검정 사각형 없이** 표시되는지 스크린샷 확인. (mac WebKit .mov는 Task 9 실기 오버레이에서 확인.)
Expected: 오브가 골든 네트워크 구로 뜨고 주변 검정 박스 없음.

- [ ] **Step 6: 커밋**

```bash
git add jarvis/hud/orb.html
git commit -m "fix(hud): 오브를 알파 영상으로 교체(엔진별 mov/webm) + SVG lumakey 필터 폐기 — WebKit 검정 박스 제거"
```

---

## Task 6: orb.html — 동적 패널 렌더러(두 모드·유동·영화 언어)

**Files:**
- Modify: `jarvis/hud/orb.html` (단일 `#notice` → 패널 컨테이너 + 렌더 함수 + CSS/SVG 장식)

- [ ] **Step 1: DOM 교체** — `<div id="notice">...</div>`를 패널 컨테이너 + 작업실 장식 레이어로 교체:

```html
  <svg id="workshop" width="0" height="0"></svg>   <!-- 리더라인/링/호 게이지(JS가 그림) -->
  <div id="panels"></div>                           <!-- 패널 카드들(JS가 렌더) -->
  <div id="gaugestrip"></div>                        <!-- 하단 5게이지 스트립(B에서만) -->
```

- [ ] **Step 2: CSS 추가** — `<style>` 안에 패널 시스템 스타일 추가(영화 언어):

```css
  /* 작업실 패널 — 시안 홀로그램. 모드별 배치는 JS가 좌표/클래스로 제어. */
  #panels{position:fixed;inset:0;pointer-events:none;z-index:6}
  .pnl{position:absolute;background:rgba(0,8,14,.85);
    border:1px solid rgba(94,224,255,.6);border-radius:3px;
    padding:.55rem .7rem;max-width:min(34vw,420px);
    color:#d8f6ff;opacity:0;transform:translateY(6px) scale(.98);
    transition:opacity .35s ease, transform .35s cubic-bezier(.2,.7,.2,1), left .4s ease, top .4s ease;
    box-shadow:0 0 0 1px rgba(94,224,255,.1),0 0 20px rgba(94,224,255,.22),0 10px 30px rgba(0,0,0,.55),inset 0 0 26px rgba(94,224,255,.07);
    text-shadow:0 0 8px rgba(94,224,255,.4);
    clip-path:polygon(0 0,calc(100% - 14px) 0,100% 14px,100% 100%,14px 100%,0 calc(100% - 14px));
    font:500 13px/1.5 ui-monospace,"SF Mono","Menlo","Malgun Gothic","Apple SD Gothic Neo",monospace}
  .pnl.show{opacity:1;transform:translateY(0) scale(1)}
  .pnl .h{font:700 10px/1 ui-monospace,"SF Mono",monospace;letter-spacing:.24em;
    color:#7fe9ff;text-transform:uppercase;margin-bottom:.4rem;display:flex;align-items:center;gap:.4rem;
    text-shadow:0 0 9px rgba(94,224,255,.6)}
  .pnl .h::before{content:"";width:6px;height:6px;border-radius:50%;background:#7fe9ff;
    box-shadow:0 0 9px #7fe9ff;animation:nblink 1.6s ease-in-out infinite}
  .pnl .b{white-space:pre-wrap;word-break:keep-all}
  .pnl.warn{border-color:rgba(255,176,46,.65)} .pnl.warn .h{color:#ffc55e}
  .pnl.warn .h::before{background:#ffc55e;box-shadow:0 0 9px #ffc55e}
  .pnl.gold{border-color:rgba(236,186,79,.6)} .pnl.gold .h{color:#ecba4f}
  .pnl.gold .h::before{background:#ecba4f;box-shadow:0 0 9px #ecba4f}
  /* 코너 브래킷(좌상) */
  .pnl::before{content:"";position:absolute;top:-1px;left:-1px;width:13px;height:13px;
    border-top:2px solid currentColor;border-left:2px solid currentColor;color:#6fe6ff;opacity:.85}
  .pnl.big{font-size:14px} .pnl.huge{font-size:15.5px;max-width:min(46vw,560px)}
  #workshop{position:fixed;inset:0;pointer-events:none;z-index:5}
  #gaugestrip{position:fixed;left:50%;bottom:4vh;transform:translateX(-50%);display:none;
    gap:18px;z-index:6;pointer-events:none}
  body.bmode #gaugestrip{display:flex}
  .g{display:flex;flex-direction:column;align-items:center;gap:3px;font:700 8px ui-monospace,monospace;
    letter-spacing:.1em;color:#7fe9ff;opacity:.8}
  .g svg{width:20px;height:20px}
```

- [ ] **Step 3: 렌더 JS 추가** — `<script>` 안, 기존 `showNotice`/`apply` 영역을 다음 렌더러로 교체(기존 `noticeEl`/`showNotice` 참조 제거, `es.onmessage`에서 `renderPanels(d.panels)` 호출):

```javascript
const panelsEl=document.getElementById("panels");
const workshopEl=document.getElementById("workshop");
const stripEl=document.getElementById("gaugestrip");
const SVGNS="http://www.w3.org/2000/svg";
let panelKeepUntil=0;

function sizeClass(p){const len=(p.body||"").length+(p.title||"").length;
  if(len>360) return "huge"; if(len>120) return "big"; return "";}

// 코너(A): 우하단 오브 위로 세로 스택. 중앙(B): 오브 둘레 방사 슬롯.
function slotsFor(n, bmode){
  if(!bmode){ // A: 우측에 아래→위로 쌓기
    const s=[]; for(let i=0;i<n;i++) s.push({right:"4vw", bottom:(16+i*16)+"vh", cx:null});
    return s;
  }
  // B: 중앙 오브 주위 8슬롯(좌상부터 시계방향), 화면 비율 기준
  const ring=[[14,16],[72,12],[78,40],[74,70],[40,80],[12,72],[8,42],[10,16]];
  return ring.slice(0,n).map(([x,y])=>({left:x+"vw",top:y+"vh",cx:x,cy:y}));
}

function renderPanels(panels){
  panels=panels||[]; const bmode=document.body.classList.contains("bmode");
  // 브레인 먼저, 텔레메트리 나중(중요도 순). 코너에선 텔레메트리 최소(clock/tasks만).
  let list=panels.slice();
  if(!bmode) list=list.filter(p=>p.kind!=="telemetry"||p.id==="clock"||p.id==="tasks");
  panelsEl.innerHTML=""; clearWorkshop();
  const slots=slotsFor(list.length,bmode);
  list.forEach((p,i)=>{
    const el=document.createElement("div");
    el.className="pnl "+(p.tone==="warn"?"warn":p.tone==="gold"?"gold":"")+" "+sizeClass(p);
    el.innerHTML='<div class="h"></div><div class="b"></div>';
    el.querySelector(".h").textContent=p.title||"";
    el.querySelector(".b").textContent=p.body||"";
    const s=slots[i]||{}; for(const k of ["left","top","right","bottom"]) if(s[k]) el.style[k]=s[k];
    panelsEl.appendChild(el);
    requestAnimationFrame(()=>el.classList.add("show"));
    if(bmode && s.cx!=null) drawLeader(s.cx,s.cy);   // 오브→패널 리더라인
  });
  drawOrbRings(bmode);
  renderStrip(panels,bmode);
  if(panels.length) panelKeepUntil=performance.now()+Math.min(45000,8000+JSON.stringify(panels).length*30);
}

function clearWorkshop(){ while(workshopEl.firstChild) workshopEl.removeChild(workshopEl.firstChild);
  workshopEl.setAttribute("width",innerWidth); workshopEl.setAttribute("height",innerHeight);
  workshopEl.setAttribute("viewBox","0 0 "+innerWidth+" "+innerHeight); }

function line(x1,y1,x2,y2,stroke,w,dash){const l=document.createElementNS(SVGNS,"line");
  l.setAttribute("x1",x1);l.setAttribute("y1",y1);l.setAttribute("x2",x2);l.setAttribute("y2",y2);
  l.setAttribute("stroke",stroke);l.setAttribute("stroke-width",w||1);if(dash)l.setAttribute("stroke-dasharray",dash);
  workshopEl.appendChild(l);return l;}
function circ(cx,cy,r,stroke,w,dash){const c=document.createElementNS(SVGNS,"circle");
  c.setAttribute("cx",cx);c.setAttribute("cy",cy);c.setAttribute("r",r);c.setAttribute("fill","none");
  c.setAttribute("stroke",stroke);c.setAttribute("stroke-width",w||1);if(dash)c.setAttribute("stroke-dasharray",dash);
  workshopEl.appendChild(c);return c;}

function orbCenter(){ // 화면상의 오브 중심 px
  const r=orbwrap.getBoundingClientRect(); return [r.left+r.width/2, r.top+r.height/2];}
function drawLeader(cxvw,cyvh){const [ox,oy]=orbCenter();
  const px=innerWidth*cxvw/100, py=innerHeight*cyvh/100;
  line(ox,oy,(ox+px)/2,py,"rgba(94,224,255,.4)",1); line((ox+px)/2,py,px,py,"rgba(94,224,255,.4)",1);
  const d=document.createElementNS(SVGNS,"circle");d.setAttribute("cx",px);d.setAttribute("cy",py);
  d.setAttribute("r",2);d.setAttribute("fill","#67C7EB");workshopEl.appendChild(d);}
function drawOrbRings(bmode){const [ox,oy]=orbCenter();const base=orbwrap.getBoundingClientRect().width/2;
  if(!bmode){circ(ox,oy,base+10,"rgba(94,224,255,.18)",1);return;}
  circ(ox,oy,base+14,"rgba(94,224,255,.2)",1);
  circ(ox,oy,base+24,"rgba(94,224,255,.28)",1,"5 9");
  circ(ox,oy,base+36,"rgba(236,186,79,.5)",1.5,"60 130");   // 골드 호 게이지(부분)
}

function gaugeSVG(label,frac,gold){return '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" fill="none" stroke="#1d3a44" stroke-width="2.5"/>'+
  '<circle cx="12" cy="12" r="9" fill="none" stroke="'+(gold?"#ecba4f":"#8effc8")+'" stroke-width="2.5" stroke-linecap="round" '+
  'stroke-dasharray="'+(56.5*frac).toFixed(1)+' 56.5" transform="rotate(-90 12 12)"/></svg><span>'+label+'</span>';}
function renderStrip(panels,bmode){ stripEl.innerHTML="";
  if(!bmode) return;
  const tel=(panels||[]).filter(p=>p.kind==="telemetry");
  tel.forEach(p=>{const g=document.createElement("div");g.className="g";
    let frac=.5,gold=p.tone==="gold"; if(p.gauge&&p.gauge.cpu!=null)frac=p.gauge.cpu/100;
    g.innerHTML=gaugeSVG((p.title||"").replace(/^[^가-힣A-Za-z]+/,"").slice(0,4),frac,gold);
    stripEl.appendChild(g);});
}
```

- [ ] **Step 4: `es.onmessage`/`apply`/frame 연동** — `es.onmessage`를 교체:

```javascript
  es.onmessage=e=>{const d=JSON.parse(e.data);apply(d.state,d.level,d.text);
    setExpand(!!d.expand || (d.panels && d.panels.some(p=>p.kind==="brain")));
    renderPanels(d.panels);};
```
`es.onerror`에서 패널도 비우게:
```javascript
  es.onerror=()=>{ state="idle"; targetLevel=0; demo=false;
    subEl.style.opacity=0; renderPanels([]); };
```
`frame()`의 presence<0.01 분기에서 기존 notice 숨김 대신:
```javascript
    if(performance.now()>panelKeepUntil) renderPanels([]);
```
(기존 `noticeEl` 참조 라인들 제거.)

- [ ] **Step 5: 수동 검증** — Chrome DevTools로 정적 서버 orb.html 열고, 콘솔에서 두 모드 주입:

```javascript
// 코너(A)
renderPanels([{kind:"brain",title:"검색 결과",body:"항목1\n항목2\n항목3",tone:"cyan"},
  {kind:"telemetry",id:"clock",title:"◷ 14:32",body:"",tone:"cyan"}]);
// 중앙(B)
document.body.classList.add("bmode"); orbwrap.classList.add("expand");
renderPanels([{kind:"brain",title:"일정",body:"3시 회의\n5시 통화",tone:"cyan"},
  {kind:"telemetry",id:"sys",title:"◰ SYS",body:"CPU 12% MEM 41%",tone:"gold",gauge:{cpu:12,mem:41}},
  {kind:"telemetry",id:"mic",title:"◇ 입력",body:"MIC ● LIVE",tone:"cyan"},
  {kind:"telemetry",id:"clock",title:"◷ 14:32",body:"",tone:"cyan"}]);
```
스크린샷으로 코너 스택 / 중앙 방사+리더라인+5게이지 확인.
Expected: 두 모드 모두 패널이 오브 기준으로 배치되고 리더라인·게이지 보임.

- [ ] **Step 6: 커밋**

```bash
git add jarvis/hud/orb.html
git commit -m "feat(hud): 작업실 패널 렌더러 — 코너 스택/중앙 방사 두 모드, 리더라인·링·5게이지, 유동 크기"
```

---

## Task 7: show_panel 멀티카드 안내 + jarvis.spec 자산 번들

**Files:**
- Modify: `jarvis/tools/jarvis_mcp.py` (`show_panel` 설명)
- Modify: `packaging/jarvis.spec` (자산 교체)

- [ ] **Step 1: show_panel 설명에 카드 구분자 안내** — `jarvis_mcp.py`의 show_panel 설명 문자열 끝에 한 문장 추가(인자는 그대로):

기존 마지막 문장 `... 도움될 때만 띄운다.` 뒤에 이어붙임:
```
"여러 항목을 별도 카드로 나누고 싶으면 카드 사이에 '---'만 있는 줄을 넣어라(각 카드 첫 줄=제목)."
```

- [ ] **Step 2: jarvis.spec 자산 교체** — 56행 부근

```python
    # HUD orb video asset (served by OrbServer at /assets/orb.mp4)
    _data(REPO_ROOT / "jarvis" / "hud" / "assets" / "orb.mp4", "jarvis/hud/assets"),
```
를:
```python
    # HUD orb — 알파 영상(엔진별): mac=HEVC .mov, win=VP9 .webm. (검정 배경이 박혀 빠짐)
    _data(REPO_ROOT / "jarvis" / "hud" / "assets" / "orb-alpha.mov", "jarvis/hud/assets"),
    _data(REPO_ROOT / "jarvis" / "hud" / "assets" / "orb-alpha.webm", "jarvis/hud/assets"),
```

- [ ] **Step 3: 자산 존재 확인**

Run: `ls -la jarvis/hud/assets/orb-alpha.mov jarvis/hud/assets/orb-alpha.webm`
Expected: 두 파일 모두 존재(각각 ~17MB·~22MB).

- [ ] **Step 4: 커밋**

```bash
git add jarvis/tools/jarvis_mcp.py packaging/jarvis.spec
git commit -m "build(hud): 알파 영상 자산 번들(orb-alpha.mov/webm) + show_panel 멀티카드(---) 안내"
```

---

## Task 8: 전체 회귀 + 실기 검증 + 정리

**Files:** (없음 — 검증 전용)

- [ ] **Step 1: 전체 테스트**

Run: `pytest tests/ -q`
Expected: 전부 PASS(기존 + 신규).

- [ ] **Step 2: 실기 오버레이 검증(mac)** — 자비스 기동 후 thinking/speaking 상태로 오브가 **검정 박스 없이** 뜨는지, `show_panel`로 패널이 코너(A)에, "크게 띄워"로 중앙(B) 방사 배치 + 텔레메트리/리더라인/5게이지가 뜨는지 육안 확인. (스크린샷)

```bash
cd /Users/2seongjae/jarvis && (nohup ./scripts/run.sh > /tmp/jarvis_verify.log 2>&1 &) ; sleep 8
```
검증 후 종료:
```bash
pkill -TERM -f "[Pp]ython -m jarvis"
```

- [ ] **Step 3: 원본 자산 정리(선택)** — `orb.mp4`는 알파 소스로 보관 가치가 있으니 삭제하지 않는다. 임시 정적 서버만 종료:

```bash
pkill -f "http.server 8799" 2>/dev/null; true
```

- [ ] **Step 4: 최종 커밋/푸시(사용자 확인 후)**

```bash
git add -A && git commit -m "feat(hud): 작업실 패널 재설계 + 오브 알파(검정 제거) 통합 완료" || true
git push origin main
```

---

## Self-Review

**Spec coverage:** ① 오브 검정 제거(알파 영상)=Task 4·5·7 ✓ ② 두 모드 코너↔중앙=Task 6(slotsFor/setExpand 재사용) ✓ ③ 패널 A+B(두뇌 멀티카드+텔레메트리)=Task 1(_brain_cards)·2·3·6 ✓ ④ 유동 크기=Task 6(sizeClass) ✓ ⑤ 영화 디자인 언어(색·링·호·리더라인·5게이지·모노)=Task 6 ✓ ⑥ SSE panels[] 데이터 흐름=Task 1 ✓ ⑦ notice 하위호환=Task 1 ✓ ⑧ jarvis.spec=Task 7 ✓.

**Placeholder scan:** 모든 코드 스텝에 실제 코드 포함. "후속(net=None)"은 의도적 비활성(가짜 데이터 금지)이며 기능 누락 아님 — collect(net=None)이 항목 생략으로 정상 처리.

**Type consistency:** 패널 dict 키(`id,title,body,kind,tone,gauge`)는 `_brain_cards`(Task1)·`collect`(Task2)·`renderPanels`(Task6) 전부 일치. `publish_telemetry`(Task1)↔`TelemetryProvider`(Task2)↔orchestrator(Task3) 호출 시그니처 일치. emit에 `panels` 키 추가가 기존 테스트와 충돌→Task1 Step4에서 갱신.
