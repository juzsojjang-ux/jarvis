# 화면 시야+제어 (3c) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 자비스가 화면을 캡처해 보고(눈), "화면 제어 모드" 게이트 안에서 마우스·키보드로 조작한다(손) — 캡처→보기→행동 루프로 화면 공유+원격 조작 체감을 만든다.

**Architecture:** 새 `ControlGate`(스레드 안전 on/off+TTL 만료, `CONTROL_GATE` 모듈 싱글턴 — `DEFAULT_BOARD` 패턴)가 안전 게이트. `jarvis_mcp.py`에 `capture_screen`(screencapture -x + 레티나 포인트 보정)과 `screen_control`(cliclick 디스패치, 게이트 off면 거부) 도구 2개 추가. 오케스트레이터는 interpret 토글과 같은 모양의 `_control_command`/`_toggle_control`로 게이트를 음성 토글. 두뇌는 Read로 캡처 이미지를 직접 본다(별도 비전 모델 없음).

**Tech Stack:** Python 3.12, pytest, macOS `screencapture`/`sips`/`osascript`, `cliclick`(brew, 런타임 검사), claude-agent-sdk `@tool`.

**Spec:** `docs/superpowers/specs/2026-06-11-screen-vision-design.md` (commit 737d70a)

**전 태스크 공통 규칙(프로젝트 불변):**
- 도구 액션 함수는 절대 raise하지 않고 한국어 안내 문자열을 반환한다.
- 테스트는 절대 실제 `screencapture`/`cliclick`/`osascript`/`say`를 실행하지 않는다 — 항상 fake runner 주입.
- 작업 디렉터리: `/Users/2seongjae/jarvis`. 테스트 실행: `python -m pytest`.

---

### Task 1: ControlGate + CONTROL_GATE 싱글턴

**Files:**
- Create: `jarvis/core/control_gate.py`
- Test: `tests/core/test_control_gate.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/core/test_control_gate.py
from jarvis.core.control_gate import CONTROL_GATE, ControlGate


def test_gate_off_by_default():
    g = ControlGate(clock=lambda: 100.0)
    assert g.is_on() is False


def test_enable_holds_until_ttl_then_expires():
    t = [100.0]
    g = ControlGate(clock=lambda: t[0])
    g.enable(300.0)
    assert g.is_on() is True
    t[0] = 399.9
    assert g.is_on() is True
    t[0] = 400.0
    assert g.is_on() is False


def test_disable_turns_off_immediately():
    t = [100.0]
    g = ControlGate(clock=lambda: t[0])
    g.enable(300.0)
    g.disable()
    assert g.is_on() is False


def test_reenable_extends_window():
    t = [100.0]
    g = ControlGate(clock=lambda: t[0])
    g.enable(300.0)
    t[0] = 350.0
    g.enable(300.0)  # 다시 켜면 새 창
    t[0] = 600.0
    assert g.is_on() is True


def test_module_singleton_exists():
    assert isinstance(CONTROL_GATE, ControlGate)
    assert CONTROL_GATE.is_on() is False  # 실시간 시계 — 기본은 꺼짐
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/core/test_control_gate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'jarvis.core.control_gate'`

- [ ] **Step 3: Write the implementation**

```python
# jarvis/core/control_gate.py
"""화면 제어 모드 게이트 — 오케스트레이터(음성 토글)와 jarvis_mcp의 screen_control
도구가 공유한다. SubscriptionBrain이 MCP 서버를 인프로세스로 만들기 때문에
TimerBoard·DEFAULT_BOARD 패턴 그대로 모듈 싱글턴(CONTROL_GATE)으로 공유한다.
도구는 asyncio 루프에서, 토글은 같은 루프지만 to_thread 접근 가능성이 있어
락으로 보호한다. 켠 채 잊는 위험을 막으려고 TTL이 지나면 스스로 꺼진다."""
from __future__ import annotations

import threading
import time


class ControlGate:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._until = 0.0

    def enable(self, ttl_s: float = 300.0) -> None:
        with self._lock:
            self._until = self._clock() + max(1.0, float(ttl_s))

    def disable(self) -> None:
        with self._lock:
            self._until = 0.0

    def is_on(self) -> bool:
        with self._lock:
            return self._clock() < self._until


# 공유 싱글턴 — 오케스트레이터가 토글하고 screen_control 도구가 확인한다.
CONTROL_GATE = ControlGate()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/core/test_control_gate.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add jarvis/core/control_gate.py tests/core/test_control_gate.py
git commit -m "feat(3c): ControlGate — 화면 제어 모드 게이트(TTL 만료, 모듈 싱글턴)"
```

---

### Task 2: 설정 screen_control_ttl_s

**Files:**
- Modify: `jarvis/core/config.py` (M5 정보 팩 블록 바로 아래, `interpret_ko_voice` 줄 다음)
- Test: `tests/core/test_config_m2.py` (기존 파일에 추가)

- [ ] **Step 1: Write the failing test** — `tests/core/test_config_m2.py` 끝에 추가:

```python
def test_screen_control_defaults():
    s = Settings()
    assert s.screen_control_ttl_s == 300.0
```

(파일 상단에 이미 `Settings` import가 있다 — `test_interpret_defaults`와 같은 방식.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/core/test_config_m2.py::test_screen_control_defaults -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'screen_control_ttl_s'`

- [ ] **Step 3: Implement** — `jarvis/core/config.py`의 M5 블록(96-97행 부근) 바로 아래에 추가:

```python
    # --- M6 화면 시야+제어 (3c) ---
    screen_control_ttl_s: float = 300.0  # "화면 제어 모드" 자동 만료(초) — 켠 채 잊기 방지
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/core/test_config_m2.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add jarvis/core/config.py tests/core/test_config_m2.py
git commit -m "feat(3c): 설정 screen_control_ttl_s=300 — 제어 모드 자동 만료"
```

---

### Task 3: capture_screen 도구 (눈)

**Files:**
- Modify: `jarvis/tools/jarvis_mcp.py` — 액션 함수는 `list_shortcuts_action`(241행 부근) 뒤에, @tool은 `_list_timers`(578행 부근) 뒤에, 등록은 `build_jarvis_mcp_server`의 `tools` 리스트와 `JARVIS_TOOL_NAMES`에
- Test: `tests/tools/test_screen.py` (새 파일)

**배경 — 레티나 좌표 보정(스펙에 없는 구현 확정 사항):** `screencapture`는 레티나에서 2배 픽셀로 캡처하지만 `cliclick`은 포인트(1배) 좌표를 쓴다. 두뇌가 이미지에서 읽은 좌표를 그대로 cliclick에 넘기면 전부 2배로 빗나간다. 그래서 캡처 직후 `osascript`로 데스크톱 포인트 너비를 얻어 `sips --resampleWidth`로 이미지를 포인트 크기로 줄인다 — 이미지 좌표 == 클릭 좌표가 된다. 보정 실패는 무시(캡처 자체는 유효).

- [ ] **Step 1: Write the failing tests**

```python
# tests/tools/test_screen.py
"""capture_screen / screen_control — 실제 screencapture·cliclick·osascript는 절대
실행하지 않는다(fake runner 주입)."""
from jarvis.tools.jarvis_mcp import capture_screen_action


class _Res:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.returncode = returncode


def _runner(calls, *, fail_capture=False):
    def run(cmd, capture_output=True, text=True):
        calls.append(list(cmd))
        if cmd[0] == "screencapture" and fail_capture:
            return _Res(returncode=1)
        if cmd[0] == "osascript":
            return _Res(stdout="0, 0, 1728, 1117\n")
        return _Res()
    return run


def test_capture_creates_dir_and_returns_path(tmp_path):
    calls = []
    target = tmp_path / "shots" / "shot.png"
    out = capture_screen_action(runner=_runner(calls), path=target)
    assert target.parent.is_dir()
    assert str(target) in out
    assert calls[0] == ["screencapture", "-x", str(target)]


def test_capture_resamples_to_point_width(tmp_path):
    calls = []
    target = tmp_path / "shot.png"
    capture_screen_action(runner=_runner(calls), path=target)
    sips = [c for c in calls if c[0] == "sips"]
    assert sips and sips[0][:3] == ["sips", "--resampleWidth", "1728"]


def test_capture_failure_returns_guidance(tmp_path):
    out = capture_screen_action(runner=_runner([], fail_capture=True),
                                path=tmp_path / "shot.png")
    assert "실패" in out and "권한" in out


def test_capture_never_raises(tmp_path):
    def boom(cmd, capture_output=True, text=True):
        raise OSError("no screen")
    out = capture_screen_action(runner=boom, path=tmp_path / "shot.png")
    assert "실패" in out


def test_capture_survives_bad_bounds(tmp_path):
    """osascript 보정 실패해도 캡처 경로는 반환."""
    def run(cmd, capture_output=True, text=True):
        if cmd[0] == "osascript":
            return _Res(stdout="garbage")
        return _Res()
    target = tmp_path / "shot.png"
    out = capture_screen_action(runner=run, path=target)
    assert str(target) in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/tools/test_screen.py -v`
Expected: FAIL — `ImportError: cannot import name 'capture_screen_action'`

- [ ] **Step 3: Implement** — `jarvis/tools/jarvis_mcp.py`.

파일 상단 import에 추가(12행 `import subprocess` 아래):

```python
from pathlib import Path
```

`list_shortcuts_action` 함수 뒤에 액션 함수 추가:

```python
_SCREENSHOT_PATH = Path.home() / ".jarvis" / "screenshots" / "shot.png"


def capture_screen_action(runner=subprocess.run, path: Path | None = None) -> str:
    """화면을 무음 캡처해 파일로 저장하고 경로를 반환한다 — 두뇌가 Read로 본다.
    레티나 캡처(2배 픽셀)를 포인트 크기로 줄여 이미지 좌표를 cliclick 좌표와
    일치시킨다(보정 실패는 무시 — 캡처 자체는 유효)."""
    target = Path(path) if path is not None else _SCREENSHOT_PATH
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        res = runner(["screencapture", "-x", str(target)],
                     capture_output=True, text=True)
        if getattr(res, "returncode", 1) != 0:
            return ("화면 캡처에 실패했습니다. 시스템 설정의 화면 기록 권한을 "
                    "확인해 주세요.")
        try:
            b = runner(["osascript", "-e",
                        'tell application "Finder" to get bounds of window of desktop'],
                       capture_output=True, text=True)
            width = int(str(b.stdout).split(",")[2].strip())
            runner(["sips", "--resampleWidth", str(width), str(target)],
                   capture_output=True, text=True)
        except Exception:  # noqa: BLE001 - 보정은 최선 노력
            pass
        return f"화면을 캡처했습니다. 이 이미지를 Read 도구로 보세요: {target}"
    except Exception:  # noqa: BLE001 - 도구는 절대 raise하지 않는다
        return "화면 캡처에 실패했습니다."
```

`_list_timers` @tool 뒤에 래퍼 추가:

```python
@tool("capture_screen",
      "맥 화면을 캡처해 이미지 파일로 저장한다. 반환된 경로를 Read 도구로 읽으면 "
      "지금 화면을 직접 볼 수 있다. 화면 조작 전 좌표 파악에도 쓴다.", {})
async def _capture_screen(_args):
    return _text(capture_screen_action())
```

`build_jarvis_mcp_server`의 `tools` 리스트에서 `_get_messages, _get_unread_mail,` 줄 다음에 `_capture_screen,` 추가. `JARVIS_TOOL_NAMES` 튜플에서 `"get_messages", "get_unread_mail",` 줄 다음에 `"capture_screen",` 추가.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/tools/test_screen.py tests/tools/test_jarvis_mcp.py -v`
Expected: all passed (기존 jarvis_mcp 테스트 포함 회귀 없음)

- [ ] **Step 5: Commit**

```bash
git add jarvis/tools/jarvis_mcp.py tests/tools/test_screen.py
git commit -m "feat(3c): capture_screen — 무음 화면 캡처+레티나 포인트 보정(눈)"
```

---

### Task 4: screen_control 도구 (손)

**Files:**
- Modify: `jarvis/tools/jarvis_mcp.py` — `capture_screen_action` 뒤에 액션, `_capture_screen` 뒤에 @tool, 두 등록 지점에 추가
- Test: `tests/tools/test_screen.py` (Task 3 파일에 추가)

**구현 확정 사항(스펙의 "스크롤 방향은 구현 시 확정"):** cliclick에는 네이티브 스크롤 명령이 없다. `kp:page-up`/`kp:page-down` 키 입력으로 구현한다 — `amount` 양수=위(page-up), 음수=아래(page-down), |amount|회 반복(최대 10회 캡). cliclick은 한 호출에 명령 여러 개를 받으므로 `["cliclick", "kp:page-down", "kp:page-down"]`처럼 한 번에 보낸다.

- [ ] **Step 1: Write the failing tests** — `tests/tools/test_screen.py`에 추가:

```python
from jarvis.core.control_gate import ControlGate
from jarvis.tools.jarvis_mcp import screen_control_action


def _gate(on=True):
    g = ControlGate(clock=lambda: 100.0)
    if on:
        g.enable(300.0)
    return g


def test_control_refused_when_gate_off():
    calls = []
    out = screen_control_action("click", x=10, y=20, gate=_gate(on=False),
                                runner=_runner(calls))
    assert "화면 제어 모드" in out
    assert calls == []  # 절대 실행되지 않는다


def test_control_click_dispatch():
    calls = []
    out = screen_control_action("click", x=10, y=20, gate=_gate(),
                                runner=_runner(calls))
    assert calls == [["cliclick", "c:10,20"]]
    assert "클릭" in out


def test_control_double_right_move_dispatch():
    for action, prefix in (("double_click", "dc"), ("right_click", "rc"), ("move", "m")):
        calls = []
        screen_control_action(action, x=5, y=7, gate=_gate(), runner=_runner(calls))
        assert calls == [["cliclick", f"{prefix}:5,7"]]


def test_control_type_dispatch():
    calls = []
    screen_control_action("type", text="안녕 jarvis", gate=_gate(), runner=_runner(calls))
    assert calls == [["cliclick", "t:안녕 jarvis"]]


def test_control_key_dispatch():
    calls = []
    screen_control_action("key", key="return", gate=_gate(), runner=_runner(calls))
    assert calls == [["cliclick", "kp:return"]]


def test_control_scroll_maps_to_page_keys():
    calls = []
    screen_control_action("scroll", amount=-2, gate=_gate(), runner=_runner(calls))
    assert calls == [["cliclick", "kp:page-down", "kp:page-down"]]
    calls.clear()
    screen_control_action("scroll", amount=3, gate=_gate(), runner=_runner(calls))
    assert calls == [["cliclick", "kp:page-up"] + ["kp:page-up"] * 2]


def test_control_scroll_caps_repeats():
    calls = []
    screen_control_action("scroll", amount=-99, gate=_gate(), runner=_runner(calls))
    assert len(calls[0]) == 1 + 10  # cliclick + 최대 10회


def test_control_bad_coords_guidance():
    out = screen_control_action("click", x="abc", y=None, gate=_gate(), runner=_runner([]))
    assert "좌표" in out


def test_control_unknown_action_guidance():
    out = screen_control_action("fly", gate=_gate(), runner=_runner([]))
    assert "지원하지 않는" in out


def test_control_missing_cliclick_guidance():
    def no_bin(cmd, capture_output=True, text=True):
        raise FileNotFoundError("cliclick")
    out = screen_control_action("click", x=1, y=1, gate=_gate(), runner=no_bin)
    assert "brew install cliclick" in out


def test_control_empty_type_and_key_guidance():
    assert "텍스트" in screen_control_action("type", text="", gate=_gate(), runner=_runner([]))
    assert "키" in screen_control_action("key", key="", gate=_gate(), runner=_runner([]))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/tools/test_screen.py -v`
Expected: 새 테스트 전부 FAIL — `ImportError: cannot import name 'screen_control_action'`

- [ ] **Step 3: Implement** — `jarvis/tools/jarvis_mcp.py`.

파일 상단 import에 추가(`from ..proactive.timers import DEFAULT_BOARD` 아래):

```python
from ..core.control_gate import CONTROL_GATE
```

`capture_screen_action` 뒤에 추가:

```python
_CLICK_PREFIX = {"click": "c", "double_click": "dc", "right_click": "rc", "move": "m"}


def screen_control_action(action: str, x: Any = None, y: Any = None, text: str = "",
                          key: str = "", amount: Any = None,
                          gate=None, runner=subprocess.run) -> str:
    """좌표 기반 화면 조작(cliclick). '화면 제어 모드' 게이트가 꺼져 있으면 거부 —
    모드 진입 자체가 사용자 동의라서 모드 안에서는 동작별 음성 확인 없이 실행한다."""
    g = gate if gate is not None else CONTROL_GATE
    if not g.is_on():
        return ("화면 제어 모드가 꺼져 있습니다. 먼저 '화면 제어 모드 켜줘'라고 "
                "말씀해 주세요.")
    action = (action or "").strip()
    if action in _CLICK_PREFIX:
        try:
            args = [f"{_CLICK_PREFIX[action]}:{int(x)},{int(y)}"]
        except (TypeError, ValueError):
            return "좌표 x, y를 정수로 알려주세요."
        done = {"click": "클릭했습니다", "double_click": "더블클릭했습니다",
                "right_click": "우클릭했습니다", "move": "이동했습니다"}[action]
    elif action == "type":
        if not (text or "").strip():
            return "입력할 텍스트가 비어 있습니다."
        args = [f"t:{text}"]
        done = "입력했습니다"
    elif action == "key":
        if not (key or "").strip():
            return "누를 키 이름이 비어 있습니다(return, tab, esc, space, arrow-down 등)."
        args = [f"kp:{key.strip()}"]
        done = f"{key.strip()} 키를 눌렀습니다"
    elif action == "scroll":
        # cliclick엔 스크롤 명령이 없다 — page-up/down 키로 구현(양수=위).
        try:
            n = int(amount if amount is not None else 1)
        except (TypeError, ValueError):
            return "스크롤 양은 정수로 알려주세요(양수 위, 음수 아래)."
        if n == 0:
            return "스크롤 양이 0입니다."
        k = "page-up" if n > 0 else "page-down"
        args = [f"kp:{k}"] * min(abs(n), 10)
        done = "스크롤했습니다"
    else:
        return ("지원하지 않는 동작입니다. click, double_click, right_click, move, "
                "type, key, scroll 중 하나를 쓰세요.")
    try:
        res = runner(["cliclick", *args], capture_output=True, text=True)
    except FileNotFoundError:
        return ("화면 제어에는 cliclick이 필요합니다. 터미널에서 "
                "brew install cliclick 을 실행해 주세요.")
    except Exception:  # noqa: BLE001 - 도구는 절대 raise하지 않는다
        return "화면 조작에 실패했습니다."
    if getattr(res, "returncode", 0) != 0:
        return "화면 조작에 실패했습니다. 손쉬운 사용(접근성) 권한을 확인해 주세요."
    return f"{done}."
```

`_capture_screen` @tool 뒤에 래퍼 추가:

```python
@tool("screen_control",
      "화면을 마우스·키보드로 조작한다(클릭/더블클릭/우클릭/이동/텍스트 입력/특수키/"
      "스크롤). 사용자가 '화면 제어 모드'를 켜둬야만 동작한다. 좌표는 먼저 "
      "capture_screen으로 화면을 본 뒤 그 이미지 픽셀 좌표를 그대로 쓴다.",
      {"type": "object", "properties": {
          "action": {"type": "string",
                     "enum": ["click", "double_click", "right_click", "move",
                              "type", "key", "scroll"]},
          "x": {"type": "integer"}, "y": {"type": "integer"},
          "text": {"type": "string"}, "key": {"type": "string"},
          "amount": {"type": "integer"}},
       "required": ["action"]})
async def _screen_control(args):
    a = args or {}
    return _text(screen_control_action(
        str(a.get("action") or ""), a.get("x"), a.get("y"),
        str(a.get("text") or ""), str(a.get("key") or ""), a.get("amount")))
```

`build_jarvis_mcp_server`의 `tools` 리스트에서 `_capture_screen,` 뒤에 `_screen_control,` 추가. `JARVIS_TOOL_NAMES`에서 `"capture_screen",` 뒤에 `"screen_control",` 추가.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/tools/ -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add jarvis/tools/jarvis_mcp.py tests/tools/test_screen.py
git commit -m "feat(3c): screen_control — cliclick 디스패치+제어모드 게이트(손)"
```

---

### Task 5: 오케스트레이터 — "화면 제어 모드" 음성 토글

**Files:**
- Modify: `jarvis/core/orchestrator.py` — `_pipeline_text`(137행 부근) 검사 순서 + 통역 모드 섹션(266행 부근) 뒤에 토글 메서드
- Test: `tests/test_orchestrator.py` (기존 파일에 추가)

**검사 순서(스펙):** ① control 토글("화면 제어"+켜/꺼) → ② interpret 토글 → ③ interpret_mode 턴 → ④ 일반 두뇌. control 모드는 턴을 가로채지 않는다 — 게이트 플래그만 열고, 두뇌는 평소 경로로 capture_screen/screen_control을 쓴다. 토글 단어는 기존 `_INTERP_ON`/`_INTERP_OFF` 튜플을 재사용한다(범용 켜/꺼 단어 목록이다).

- [ ] **Step 1: Write the failing tests** — `tests/test_orchestrator.py` 끝에 추가:

```python
def test_control_command_toggles_gate_on_off(monkeypatch):
    from jarvis.core import orchestrator as orch_mod
    orch, pb = _make()
    calls = []

    class _FakeGate:
        def enable(self, ttl):
            calls.append(("enable", ttl))

        def disable(self):
            calls.append(("disable",))

    monkeypatch.setattr(orch_mod, "CONTROL_GATE", _FakeGate())

    async def run():
        await orch._pipeline_text("화면 제어 모드 켜줘")
        await orch._pipeline_text("화면 제어 모드 꺼줘")

    asyncio.run(run())
    assert calls == [("enable", orch.settings.screen_control_ttl_s), ("disable",)]
    assert len(pb.feeds) >= 1  # 안내 발화
    assert orch.state == State.IDLE


def test_control_command_matching():
    orch, _ = _make()
    assert orch._control_command("화면 제어 모드 켜줘") == "on"
    assert orch._control_command("화면제어 켜") == "on"
    assert orch._control_command("화면 제어 모드 꺼줘") == "off"
    assert orch._control_command("화면 제어 그만") == "off"
    assert orch._control_command("통역 모드 켜줘") is None
    assert orch._control_command("화면에 뭐 있어") is None


def test_control_toggle_does_not_hijack_normal_turns(monkeypatch):
    """control 모드는 interpret과 달리 턴을 가로채지 않는다 — 토글 후 일반
    질문은 평소처럼 두뇌로 간다."""
    from jarvis.core import orchestrator as orch_mod

    class _FakeGate:
        def enable(self, ttl):
            pass

        def disable(self):
            pass

    monkeypatch.setattr(orch_mod, "CONTROL_GATE", _FakeGate())
    orch, pb = _make()

    async def run():
        await orch._pipeline_text("화면 제어 모드 켜줘")
        await orch._pipeline_text("안녕")  # 일반 두뇌 경로

    asyncio.run(run())
    assert orch.state == State.IDLE
    assert len(pb.feeds) >= 2  # 토글 안내 + 두뇌 답변 둘 다 발화됨


def test_control_command_checked_before_interpret(monkeypatch):
    """'화면 제어'가 들어간 토글은 interpret_mode 중에도 control 토글로 잡힌다."""
    from jarvis.core import orchestrator as orch_mod
    calls = []

    class _FakeGate:
        def enable(self, ttl):
            calls.append("enable")

        def disable(self):
            calls.append("disable")

    monkeypatch.setattr(orch_mod, "CONTROL_GATE", _FakeGate())
    orch, pb = _make()
    _interp(orch)  # 통역 모드 중

    async def run():
        await orch._pipeline_text("화면 제어 모드 켜줘")

    asyncio.run(run())
    assert calls == ["enable"]
    assert orch.interpret_mode is True  # 통역 모드는 건드리지 않는다
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_orchestrator.py -k control -v`
Expected: FAIL — `AttributeError: ... '_control_command'` / `module ... has no attribute 'CONTROL_GATE'`

- [ ] **Step 3: Implement** — `jarvis/core/orchestrator.py`.

import 추가(기존 `from .interpret import ...` 또는 다른 core import 근처):

```python
from .control_gate import CONTROL_GATE
```

`_pipeline_text`(137행 부근)의 검사부를 다음으로 교체 — control 검사가 interpret보다 먼저:

```python
    async def _pipeline_text(self, text: str, *, ack: bool = True) -> None:
        if not text.strip():
            self._to_idle()
            return
        ctl = self._control_command(text)
        if ctl is not None:
            await self._toggle_control(ctl)
            return
        cmd = self._interpret_command(text)
        if cmd is not None:
            await self._toggle_interpret(cmd)
            return
        if self.interpret_mode:
            await self._interpret_turn(text)
            return
```

(이후 `self.state = State.THINKING` 부터는 기존 그대로.)

통역 모드 섹션(`_toggle_interpret` 뒤, `_interpret_turn` 앞 또는 뒤)에 추가:

```python
    # ----- 화면 제어 모드 (3c) -----
    def _control_command(self, text: str) -> str | None:
        if "화면 제어" not in text and "화면제어" not in text:
            return None
        if any(w in text for w in self._INTERP_OFF):
            return "off"
        if any(w in text for w in self._INTERP_ON):
            return "on"
        return None

    async def _toggle_control(self, cmd: str) -> None:
        # interpret과 달리 턴을 가로채는 모드가 아니다 — 게이트 플래그만 연다.
        # 두뇌는 평소 경로에서 capture_screen/screen_control을 쓴다.
        if cmd == "on":
            CONTROL_GATE.enable(self.settings.screen_control_ttl_s)
            en, ko = ("Screen control engaged, sir. It will switch itself off "
                      "in a few minutes.",
                      "화면 제어 모드를 켰습니다. 잠시 후 자동으로 꺼집니다.")
        else:
            CONTROL_GATE.disable()
            en, ko = ("Screen control disengaged, sir.", "화면 제어 모드를 껐습니다.")
        await self._play_phrase(en, ko)
        await self._finish_speaking("")
        self.state = State.IDLE
        if self.wake is not None:
            self._enter_attentive()
        else:
            self._publish("idle")
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_orchestrator.py -v`
Expected: all passed (기존 interpret 테스트 포함 회귀 없음)

- [ ] **Step 5: Commit**

```bash
git add jarvis/core/orchestrator.py tests/test_orchestrator.py
git commit -m "feat(3c): '화면 제어 모드' 음성 토글 — 게이트 enable/disable+안내"
```

---

### Task 6: 두뇌 지침 — 화면 보기·조작 안내 1문장

**Files:**
- Modify: `jarvis/brain/subscription.py` — `_GUIDANCE_EN`(57행 부근)과 `_GUIDANCE_KO`(43행 부근)
- Test: `tests/brain/` 기존 가이던스 테스트 회귀 확인만(새 테스트는 문구 검사 1개)

- [ ] **Step 1: Write the failing test** — `tests/brain/`의 가이던스를 다루는 기존 테스트 파일(`grep -rln "_GUIDANCE" tests/brain/` 으로 찾는다)에 추가. 없으면 `tests/brain/test_guidance_screen.py` 새로 만든다:

```python
from jarvis.brain.subscription import _GUIDANCE_EN, _GUIDANCE_KO


def test_guidance_mentions_screen_tools():
    for g in (_GUIDANCE_EN, _GUIDANCE_KO):
        assert "capture_screen" in g
        assert "screen_control" in g
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/brain/ -k screen -v`
Expected: FAIL — assert 실패

- [ ] **Step 3: Implement**

`_GUIDANCE_EN`의 remember 문장(`"transient context, or sensitive data. "`) 뒤에 추가:

```python
    "When sir asks about what is on the screen, call capture_screen and Read the "
    "returned image. To operate the screen (click, type, scroll), capture first to "
    "find pixel coordinates, then use screen_control — it only works while sir has "
    "said '화면 제어 모드 켜줘'; if it refuses, tell him to enable the mode. "
```

`_GUIDANCE_KO`의 마지막 문장(`"일시적 맥락·민감정보는 저장하지 마라. "`) 뒤에 추가:

```python
    "화면에 뭐가 있는지 물으면 capture_screen을 호출해 반환된 이미지를 Read로 보라. "
    "화면 조작(클릭·입력·스크롤)이 필요하면 먼저 캡처해 좌표를 본 뒤 screen_control을 "
    "쓰되, 사용자가 '화면 제어 모드'를 켜둬야 동작한다 — 거부되면 모드를 켜 달라고 하라. "
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/brain/ -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add jarvis/brain/subscription.py tests/brain/
git commit -m "feat(3c): 두뇌 지침 — capture_screen→Read, screen_control 게이트 안내"
```

---

### Task 7: 전체 검증 + 라이브 준비

**Files:** 없음(검증만)

- [ ] **Step 1: Run the entire test suite**

Run: `python -m pytest`
Expected: 전부 통과(3b 종료 시점 347개 + 신규 ~25개). 실패가 있으면 고치고 다시 실행.

- [ ] **Step 2: Import smoke** — 등록 누락 검사

Run: `python -c "from jarvis.tools.jarvis_mcp import JARVIS_TOOL_NAMES, build_jarvis_mcp_server; assert 'mcp__jarvis__capture_screen' in JARVIS_TOOL_NAMES and 'mcp__jarvis__screen_control' in JARVIS_TOOL_NAMES; build_jarvis_mcp_server(); print('OK', len(JARVIS_TOOL_NAMES))"`
Expected: `OK 28`

- [ ] **Step 3: cliclick 설치**

Run: `which cliclick || brew install cliclick`
Expected: cliclick 경로 출력. (도구는 미설치에도 안내 문자열로 동작하지만 라이브에는 필요하다.)

- [ ] **Step 4: Commit (수정이 있었던 경우만)**

```bash
git add -A && git commit -m "test(3c): 전체 스위트 통과 검증"
```

- [ ] **Step 5: 라이브 체크리스트(사용자와 함께)**

1. 자비스 실행 → "자비스, 지금 화면에 뭐 있어?" → 캡처+Read로 화면 설명 (첫 사용 시 화면 기록 권한 팝업 허용)
2. "화면 제어 모드 켜줘" → 안내 발화 확인
3. "메모 앱 열어서 안녕이라고 적어줘" → 캡처→클릭→입력 (첫 사용 시 손쉬운 사용 권한 팝업 허용)
4. "화면 제어 모드 꺼줘" → 이후 screen_control 거부 확인
