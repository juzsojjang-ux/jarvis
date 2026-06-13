# HUD·오브 재디자인 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 자비스 HUD를 영상 오브(검정 제거) + 음성 반응 + 시안 작업실 패널 + A↔B(이벤트 전환)로 재구성한다.

**Architecture:** `orb.html`이 `<video>` 오브를 `mix-blend-mode:screen`으로 띄워 검정을 제거하고, 기존 SSE `{state,level,text,notice}`의 `level`로 스케일·글로우·코어를 반응시킨다. A(우하단 작게)↔B(중앙 크게+패널)는 자동이 아니라 `notice` 등장 또는 `expand` 명령으로만 전환. `orb_server`가 `/assets/orb.mp4`를 서빙하고 spec이 자산을 번들한다.

**Tech Stack:** stdlib HTTP/SSE, HTML/CSS/JS(Canvas는 제거하고 video+DOM), PyInstaller spec, pytest.

---

### Task 1: 오브 영상 자산 서빙 (orb_server)

**Files:**
- Asset(생성됨): `jarvis/hud/assets/orb.mp4` (네이티브 1600², 6초 루프)
- Modify: `jarvis/hud/orb_server.py` (GET 핸들러에 `/assets/orb.mp4` 라우트)
- Test: `tests/hud/test_orb_server.py`

- [ ] **Step 1: 실패 테스트 작성** — `/assets/orb.mp4` GET이 video/mp4로 응답

```python
def test_serves_orb_asset(tmp_path):
    from jarvis.hud.orb_server import OrbServer
    srv = OrbServer(); srv.start()
    try:
        import urllib.request
        base = f"http://127.0.0.1:{srv.port}"
        r = urllib.request.urlopen(base + "/assets/orb.mp4")
        assert r.status == 200
        assert r.headers["Content-Type"] == "video/mp4"
        assert int(r.headers["Content-Length"]) > 100000   # 실제 영상
    finally:
        srv.stop()
```

- [ ] **Step 2: 실패 확인** — `pytest tests/hud/test_orb_server.py::test_serves_orb_asset -v` → 404로 FAIL

- [ ] **Step 3: 라우트 구현** — orb_server `_make_handler`의 do_GET에 추가(ORB_HTML 옆 assets):

```python
# 파일 상단(ORB_HTML 근처)
ORB_ASSET = Path(__file__).resolve().parent / "assets" / "orb.mp4"

# do_GET 안, "/" 분기 뒤에:
elif self.path == "/assets/orb.mp4":
    try:
        data = ORB_ASSET.read_bytes()
    except Exception:
        self.send_error(404); return
    self.send_response(200)
    self.send_header("Content-Type", "video/mp4")
    self.send_header("Content-Length", str(len(data)))
    self.send_header("Cache-Control", "max-age=86400")
    self.end_headers()
    self.wfile.write(data)
```

- [ ] **Step 4: 통과 확인** — 같은 테스트 PASS

- [ ] **Step 5: 커밋** — `git add jarvis/hud/assets/orb.mp4 jarvis/hud/orb_server.py tests/hud/test_orb_server.py && git commit -m "feat(hud): 오브 영상 자산 서빙(/assets/orb.mp4)"`

---

### Task 2: orb.html — 영상 오브 레이어 + 검정 제거 + 음성 반응

**Files:**
- Modify: `jarvis/hud/orb.html` (Canvas 오브 제거 → video+glow DOM, apply()에서 level 반응)
- 검증: headless 렌더(`/tmp`에서 #t 프레임) + 라이브

이 작업은 시각이라 렌더-검증 체크포인트로 진행한다(단위테스트 대신).

- [ ] **Step 1: DOM 추가** — `<body>`에 오브 컨테이너(캔버스 위/대신):

```html
<div id="orbwrap">
  <div id="orbglow"></div>
  <video id="orbvid" src="/assets/orb.mp4" autoplay loop muted playsinline></video>
  <div id="orbcore"></div>
</div>
```

- [ ] **Step 2: CSS** — 검정 제거(screen) + 기본 위치(A, 우하단 작게):

```css
#orbwrap{position:fixed;right:5vw;bottom:9vh;width:200px;height:200px;
  transition:all .4s cubic-bezier(.2,.7,.2,1);pointer-events:none;z-index:5;
  display:flex;align-items:center;justify-content:center;opacity:0}
#orbwrap.present{opacity:1}
#orbvid{width:100%;height:100%;object-fit:contain;mix-blend-mode:screen;
  transform:scale(var(--orbscale,1));transition:transform .08s linear;
  filter:brightness(var(--orbbright,1))}
#orbglow{position:absolute;width:160%;height:160%;border-radius:50%;
  background:radial-gradient(circle,rgba(255,180,70,var(--glow,0)) 0%,
    rgba(255,120,30,calc(var(--glow,0)*.4)) 45%,transparent 70%);
  mix-blend-mode:screen;transition:opacity .12s}
#orbcore{position:absolute;width:30%;height:30%;border-radius:50%;
  background:radial-gradient(circle,rgba(255,240,200,var(--core,0)),transparent 70%);
  mix-blend-mode:screen}
/* B 모드 — 중앙 크게 */
#orbwrap.expand{right:50%;bottom:50%;transform:translate(50%,50%);
  width:46vh;height:46vh}
```

- [ ] **Step 3: JS** — apply()에서 level로 CSS 변수 갱신(밝기는 은은하게):

```javascript
const orbwrap=document.getElementById("orbwrap");
function reactOrb(){
  // presence>0이면 표시. level로 스케일·글로우·코어·밝기(약하게).
  orbwrap.classList.toggle("present", presence>0.02);
  const lv=level;  // 0..1 (음성 크기)
  orbwrap.style.setProperty("--orbscale", (1+0.20*lv).toFixed(3));
  orbwrap.style.setProperty("--glow", (0.12+0.5*lv).toFixed(3));
  orbwrap.style.setProperty("--core", (0.15+0.55*lv).toFixed(3));
  orbwrap.style.setProperty("--orbbright", (1+0.10*lv).toFixed(3)); // 은은
}
// 기존 rAF 루프(draw) 안에서 매 프레임 reactOrb() 호출. 기존 canvas 오브 그리기는 제거.
```

- [ ] **Step 4: 기존 Canvas 오브 제거** — `#hud` 캔버스에 그리던 오브/링/코어 드로잉 코드 삭제(자막·notice·presence 로직은 유지). 배경은 투명 유지.

- [ ] **Step 5: 렌더 검증** — headless로 idle/말하기(level=0.8) 프레임 확인:

```bash
# orb_server 없이 단독 확인용으로 /assets 경로를 file로 바꿔 임시 렌더하거나,
# 라이브 자비스로 확인. 최소: 자비스 띄워 "자비스" 호출 시 오브가 우하단에 뜨고
# 말할 때 커지고 밝아지는지 육안 확인.
```

- [ ] **Step 6: 커밋** — `git add jarvis/hud/orb.html && git commit -m "feat(hud): 영상 오브 레이어 + 검정 제거(screen) + 음성 반응(스케일/글로우/코어)"`

---

### Task 3: A↔B 전환 — notice 등장 또는 expand 명령에서만

**Files:**
- Modify: `jarvis/hud/orb.html` (notice 표시 시 expand, expand 플래그 처리)
- Modify: `jarvis/hud/orb_server.py` (publish에 `expand` 필드 추가, _emit에 포함)
- Test: `tests/hud/test_orb_server.py`

- [ ] **Step 1: 실패 테스트** — publish(expand=True)가 이벤트에 expand=true 포함

```python
def test_publish_includes_expand():
    from jarvis.hud.orb_server import OrbHub
    hub = OrbHub()
    evt = hub.publish("speaking", 0.5, expand=True)
    assert evt["expand"] is True
    evt2 = hub.publish("idle", 0.0)
    assert evt2["expand"] is False   # 기본 False, 명시 안 하면 유지 안 함
```

- [ ] **Step 2: 실패 확인** — `pytest ...::test_publish_includes_expand -v` → FAIL(expand 키 없음)

- [ ] **Step 3: orb_server 구현** — `_last`/`_emit`/`publish`에 expand 추가:

```python
# __init__: self._last 에 "expand": False 추가
# publish 시그니처: def publish(self, state, level=0.0, text=None, notice=None, expand=None):
#   if expand is not None: self._expand = bool(expand)   # __init__에 self._expand=False
# _emit: evt에 "expand": self._expand 추가
```

- [ ] **Step 4: 통과 확인** — 테스트 PASS

- [ ] **Step 5: orb.html JS** — expand 플래그 + notice 등장 시 B로:

```javascript
// apply()에 expand 인자 추가, showNotice에서 내용 있으면 강제 expand.
let wantExpand=false;
function setExpand(on){ wantExpand=on; orbwrap.classList.toggle("expand", on);
  document.body.classList.toggle("bmode", on); }
// es.onmessage: const d=JSON.parse(...); apply(d.state,d.level,d.text);
//   showNotice(d.notice); setExpand(!!d.expand || (d.notice&&d.notice.length>0));
```

- [ ] **Step 6: 렌더/라이브 검증** — 패널 뜨면 중앙으로 커지고, 닫히면 우하단으로 복귀

- [ ] **Step 7: 커밋** — `git commit -m "feat(hud): A↔B 전환을 notice/expand에서만(자동 아님)"`

---

### Task 4: 시안 작업실 홀로그램 패널 스타일

**Files:**
- Modify: `jarvis/hud/orb.html` (`#notice` 및 B모드 패널 스타일을 작업실 홀로그램으로)

- [ ] **Step 1: CSS 개선** — 반투명·모서리 컷·시안 글로우·코너 브래킷·룰라인(기존 notice 스타일을 영화 홀로그램으로 강화). B모드(`body.bmode`)에서 패널 위치/크기 키움.

```css
#notice{ /* 기존 + */ clip-path:polygon(0 0,calc(100% - 16px) 0,100% 16px,100% 100%,16px 100%,0 calc(100% - 16px)); }
body.bmode #notice{ font-size:1.05em; right:5vw; top:18vh; }
```

- [ ] **Step 2: 렌더 검증** — 패널이 시안 홀로그램으로 보이는지

- [ ] **Step 3: 커밋** — `git commit -m "feat(hud): 패널 시안 작업실 홀로그램 스타일"`

---

### Task 5: "크게/작게" 음성 명령 → expand 전환

**Files:**
- Modify: `jarvis/core/orchestrator.py` (명령 매처 + publish(expand=) 호출)
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: 실패 테스트** — 매처가 확장/축소 명령 인식

```python
def test_expand_command_matches():
    from jarvis.core.orchestrator import Orchestrator
    m = Orchestrator._expand_command
    class T: pass
    assert m(T(), "크게 띄워") is True
    assert m(T(), "패널 크게") is True
    assert m(T(), "작게 해") is False
    assert m(T(), "오늘 날씨") is None
```

- [ ] **Step 2: 실패 확인** — FAIL(메서드 없음)

- [ ] **Step 3: 구현** — orchestrator에 매처 + 디스패치(`_pipeline_text`의 명령 분기에):

```python
def _expand_command(self, text: str):
    t = text.replace(" ", "")
    if any(w in t for w in ("크게띄워","크게보여","패널크게","확대")): return True
    if any(w in t for w in ("작게","축소","줄여","패널꺼")) and "화면" not in t: return False
    return None

# _pipeline_text 명령 분기에 추가:
ex = self._expand_command(text)
if ex is not None:
    if self.hud is not None: self.hud.publish(self.state.value if hasattr(self.state,'value') else 'idle', 0.0, expand=ex)
    await self._play_phrase("Very well, sir.", "크게 띄웠습니다." if ex else "작게 했습니다.")
    self._to_idle(); return
```

- [ ] **Step 4: 통과 확인** — 테스트 PASS

- [ ] **Step 5: 커밋** — `git commit -m "feat(hud): '크게/작게' 음성 명령으로 A↔B 전환"`

---

### Task 6: PyInstaller 번들 + 통합 검증

**Files:**
- Modify: `packaging/jarvis.spec` (orb.mp4 자산 datas에 추가)
- Modify: `jarvis/hud/orb_server.py` (frozen에서 자산 경로 = _MEIPASS 우선)

- [ ] **Step 1: spec datas** — `_data(REPO_ROOT/"jarvis"/"hud"/"assets"/"orb.mp4", "jarvis/hud/assets")` 추가

- [ ] **Step 2: orb_server 경로** — frozen이면 `Path(sys._MEIPASS)/"jarvis/hud/assets/orb.mp4"`, 아니면 현 경로:

```python
def _orb_asset_path():
    mp = getattr(sys, "_MEIPASS", None)
    if mp:
        p = Path(mp)/"jarvis"/"hud"/"assets"/"orb.mp4"
        if p.exists(): return p
    return Path(__file__).resolve().parent/"assets"/"orb.mp4"
```

- [ ] **Step 3: 전체 테스트** — `.venv/bin/python -m pytest -q` 전부 통과

- [ ] **Step 4: 라이브 검증** — 자비스 띄워 A 등장 → 말하기 반응 → 패널 시 B 전환 → "작게" 시 A 복귀 육안 확인. 맥 투명 오버레이.

- [ ] **Step 5: 커밋·푸시** — `git commit -m "build(hud): 오브 영상 자산 번들 + frozen 경로" && git push`

---

## Self-Review

- **Spec 커버리지**: A↔B(이벤트만)=Task3/5 ✓, 영상오브+검정제거=Task2 ✓, 음성반응(밝기 약화)=Task2 ✓, 시안패널=Task4 ✓, 자산 최고화질+번들=Task1/6 ✓, 맥/윈도우 공통=orb.html 단일+Task6 ✓.
- **자산 메모**: orb.mp4는 14MB(네이티브 1600²). 번들 크기 증가 감수(사용자 최고화질 요청).
- **시각 작업**: Task2/3/4는 단위테스트 대신 렌더/라이브 검증 — 프런트엔드 특성상 정상.
