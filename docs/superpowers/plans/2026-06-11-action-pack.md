# 액션 팩(3a) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 음성 일상 액션 5종 — 타이머(완료 시 자비스가 음성 알림), 시스템 토글, 클립보드 읽기/쓰기, macOS 단축어 실행, 음악 라이브러리 지정 재생.

**Architecture:** 전부 기존 jarvis_mcp 패턴(모듈 레벨 액션 함수 + 주입형 runner + @tool 래퍼 + JARVIS_TOOL_NAMES). 타이머만 신규 구조: `TimerBoard` 공유 객체(락 보호)를 MCP 도구(등록/취소)와 `TimerMonitor`(만기 수확→능동 엔진)가 함께 쓴다. **핵심 제약: SubscriptionBrain이 `build_jarvis_mcp_server(memory)`를 직접 호출하므로(subscription.py:160) 보드는 모듈 싱글턴 `DEFAULT_BOARD`로 공유**(서버는 인프로세스라 같은 객체). 엔진은 `cooldown_overrides`로 timer_done의 10분 쿨다운을 면제.

**Tech Stack:** osascript/networksetup/blueutil/pbpaste·pbcopy/shortcuts CLI/pmset, 기존 ProactiveEngine.

**스펙:** `docs/superpowers/specs/2026-06-11-action-pack-design.md`

**프로젝트 약속:** 테스트 `cd ~/jarvis && .venv/bin/python -m pytest <path> -v` / 린트 `.venv/bin/ruff check jarvis tests`(line 100) / 커밋 한국어 + `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` 푸터 / 주석은 '왜'만 / 라이브 앱 재시작 금지(컨트롤러 담당), **테스트는 실제 osascript·CLI 절대 호출 금지(runner 주입)**.

## 파일 구조

| 파일 | 책임 |
|---|---|
| Create `jarvis/proactive/timers.py` | `TimerBoard`(락 보호) + `DEFAULT_BOARD` 싱글턴 |
| Modify `jarvis/proactive/monitors.py` | `TimerMonitor` + `build_monitors(settings, timers=None)` |
| Modify `jarvis/proactive/engine.py` | `cooldown_overrides` 파라미터 |
| Modify `jarvis/tools/jarvis_mcp.py` | 액션 함수 9개 + @tool 9개 + 등록 |
| Modify `jarvis/__main__.py` | DEFAULT_BOARD 배선 + cooldown_overrides |
| Test | `tests/proactive/test_timers.py`(신규), test_monitors/test_engine/test_jarvis_mcp/test_main_wiring 확장 |

---

### Task 1: TimerBoard

**Files:**
- Create: `jarvis/proactive/timers.py`
- Test: `tests/proactive/test_timers.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/proactive/test_timers.py
from jarvis.proactive.timers import TimerBoard


def _board():
    t = {"v": 0.0}
    return TimerBoard(clock=lambda: t["v"]), t


def test_add_and_pop_due_in_order():
    board, t = _board()
    board.add(10, "라면")
    board.add(5, "달걀")
    assert board.pop_due() == []          # 아직 아무것도 안 됨
    t["v"] = 6.0
    assert board.pop_due() == ["달걀"]     # 5초짜리만
    t["v"] = 11.0
    assert board.pop_due() == ["라면"]
    assert board.pop_due() == []          # 수확 후 비움


def test_default_label_and_min_duration():
    board, t = _board()
    _tid, label = board.add(0, "")
    assert label == "타이머"
    t["v"] = 1.0                          # 최소 1초로 보정됨
    assert board.pop_due() == ["타이머"]


def test_listing_remaining_seconds():
    board, t = _board()
    board.add(90, "회의")
    t["v"] = 30.0
    assert board.listing() == [("회의", 60)]


def test_cancel_by_label_substring():
    board, _ = _board()
    board.add(60, "라면 타이머")
    assert "취소" in board.cancel("라면")
    assert board.listing() == []


def test_cancel_without_label():
    board, _ = _board()
    assert "없습니다" in board.cancel("")          # 아무것도 없음
    board.add(60, "하나")
    assert "'하나'" in board.cancel("")            # 1개면 그것
    board.add(60, "a")
    board.add(60, "b")
    out = board.cancel("")
    assert "여러 개" in out and "a" in out         # 여럿이면 안내
    assert "찾지 못했습니다" in board.cancel("없는라벨")
```

- [ ] **Step 2: 실패 확인** — `.venv/bin/python -m pytest tests/proactive/test_timers.py -v` → ModuleNotFoundError

- [ ] **Step 3: 구현**

```python
# jarvis/proactive/timers.py
"""음성 타이머 보드 — MCP 도구(등록/취소/목록)와 TimerMonitor(만기 수확)가
공유한다. SubscriptionBrain이 build_jarvis_mcp_server(memory)를 직접 만들기
때문에 보드는 모듈 싱글턴(DEFAULT_BOARD)으로 공유한다(서버는 인프로세스 —
같은 객체다). 도구는 asyncio 루프에서, 모니터는 to_thread에서 접근하므로
락으로 보호한다."""
from __future__ import annotations

import itertools
import threading
import time


class TimerBoard:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._seq = itertools.count(1)
        self._timers: dict[int, tuple[str, float]] = {}  # id -> (라벨, 만기시각)

    def add(self, seconds: float, label: str = "") -> tuple[int, str]:
        label = (label or "").strip() or "타이머"
        with self._lock:
            tid = next(self._seq)
            self._timers[tid] = (label, self._clock() + max(1.0, float(seconds)))
        return tid, label

    def cancel(self, label: str = "") -> str:
        """라벨 부분일치 취소. 생략 시: 1개면 그것, 여럿이면 목록 안내."""
        with self._lock:
            if not self._timers:
                return "진행 중인 타이머가 없습니다."
            label = (label or "").strip()
            if not label:
                if len(self._timers) == 1:
                    tid, (lb, _) = next(iter(self._timers.items()))
                    del self._timers[tid]
                    return f"'{lb}' 타이머를 취소했습니다."
                names = ", ".join(lb for lb, _ in self._timers.values())
                return f"타이머가 여러 개입니다({names}) — 어느 것을 취소할까요?"
            for tid, (lb, _) in list(self._timers.items()):
                if label in lb:
                    del self._timers[tid]
                    return f"'{lb}' 타이머를 취소했습니다."
            return f"'{label}' 타이머를 찾지 못했습니다."

    def listing(self) -> list[tuple[str, int]]:
        now = self._clock()
        with self._lock:
            return [(lb, max(0, int(due - now))) for lb, due in self._timers.values()]

    def pop_due(self) -> list[str]:
        """만기된 타이머 라벨을 꺼내고 보드에서 제거(1회성)."""
        now = self._clock()
        out: list[str] = []
        with self._lock:
            for tid, (lb, due) in list(self._timers.items()):
                if now >= due:
                    out.append(lb)
                    del self._timers[tid]
        return out


# 공유 싱글턴 — 배선(__main__)과 jarvis_mcp 기본값이 같은 보드를 쓴다.
DEFAULT_BOARD = TimerBoard()
```

- [ ] **Step 4: 통과 확인** — 5 PASS, ruff clean
- [ ] **Step 5: Commit** — `feat(proactive): TimerBoard — 음성 타이머 공유 보드` (+푸터)

---

### Task 2: 엔진 cooldown_overrides

**Files:**
- Modify: `jarvis/proactive/engine.py`
- Modify: `tests/proactive/test_engine.py`

- [ ] **Step 1: 실패하는 테스트 추가** — test_engine.py 끝에 (기존 헬퍼 `_Mon`/`_ann`/`_run` 재사용, `_engine` 헬퍼는 cooldown_overrides 인자를 안 받으므로 직접 구성):

```python
def test_cooldown_override_allows_back_to_back():
    spoken = []

    async def announce(prompt):
        spoken.append(prompt)

    eng = ProactiveEngine(
        [_Mon([[_ann("timer_done", 1, 0.0, prompt="달걀")], [],
               [_ann("timer_done", 1, 0.0, prompt="라면")]])],
        announce=announce, can_speak=lambda: True,
        clock=lambda: 0.0, cooldown_s=999.0, tick_s=0.01,
        cooldown_overrides={"timer_done": 0.0})
    _run(eng)
    assert spoken == ["달걀", "라면"]      # 타이머는 쿨다운 면제 — 연달아 알림
```

- [ ] **Step 2: 실패 확인** — TypeError (unexpected keyword 'cooldown_overrides')
- [ ] **Step 3: 구현** — engine.py:

`__init__` 시그니처에 `cooldown_overrides: dict[str, float] | None = None` 추가(`tick_s` 뒤), 본문에:

```python
        # kind별 쿨다운 예외 — 타이머처럼 연속 발생이 정상인 종류는 0으로.
        self._cooldown_overrides = dict(cooldown_overrides or {})
```

`_pick`의 ready 필터를:

```python
        ready = [a for a in self._pending
                 if now - self._last_spoken.get(a.kind, -1e12)
                 >= self._cooldown_overrides.get(a.kind, self._cooldown_s)]
```

- [ ] **Step 4: 통과 확인** — test_engine.py 전체(9개) PASS
- [ ] **Step 5: Commit** — `feat(proactive): 엔진 kind별 쿨다운 예외(cooldown_overrides)` (+푸터)

---

### Task 3: TimerMonitor + build_monitors(timers=)

**Files:**
- Modify: `jarvis/proactive/monitors.py`
- Modify: `tests/proactive/test_monitors.py`

- [ ] **Step 1: 실패하는 테스트 추가** — test_monitors.py (import에 `TimerMonitor` 추가, `from jarvis.proactive.timers import TimerBoard`):

```python
def test_timer_monitor_announces_due_once():
    t = {"v": 0.0}
    board = TimerBoard(clock=lambda: t["v"])
    mon = TimerMonitor(board, clock=lambda: t["v"])
    board.add(5, "달걀")
    assert mon.poll() == []
    t["v"] = 6.0
    out = mon.poll()
    assert len(out) == 1 and out[0].kind == "timer_done" and "달걀" in out[0].prompt
    assert out[0].priority == 1 and out[0].expires_at == 6.0 + 120
    assert mon.poll() == []                        # pop_due가 1회성


def test_build_monitors_includes_timer_when_board_given():
    class _S:
        battery_warn_levels = [20, 10, 5]
        reminder_lead_min = 10
        event_lead_min = 10
        greet_cooldown_h = 4.0
        briefing_expire_h = 2.0
        proactive_late_night = False

    kinds = [type(m).__name__ for m in build_monitors(_S())]
    assert "TimerMonitor" not in kinds             # 보드 없으면 미포함(하위호환)
    kinds = [type(m).__name__ for m in build_monitors(_S(), timers=TimerBoard())]
    assert "TimerMonitor" in kinds
```

- [ ] **Step 2: 실패 확인** — ImportError TimerMonitor
- [ ] **Step 3: 구현** — monitors.py에 추가:

```python
class TimerMonitor:
    """TimerBoard 만기 수확 — 타이머는 초 단위 체감이라 1초 폴링."""

    interval_s = 1.0

    def __init__(self, board, clock=time.monotonic):
        self._board = board
        self._clock = clock

    def poll(self) -> list[Announcement]:
        now = self._clock()
        return [Announcement("timer_done", f"타이머 종료: {lb}", 1, now, now + 120)
                for lb in self._board.pop_due()]
```

`build_monitors` 시그니처를 `def build_monitors(settings, timers=None) -> list:`로 바꾸고, mons 리스트 구성 후 `if settings.proactive_late_night:` 블록 앞에:

```python
    if timers is not None:
        mons.append(TimerMonitor(timers))
```

- [ ] **Step 4: 통과 확인** — test_monitors.py 전체 PASS (기존 build_monitors 테스트 포함)
- [ ] **Step 5: Commit** — `feat(proactive): TimerMonitor — 만기 타이머를 능동 알림으로` (+푸터)

---

### Task 4: MCP 타이머 도구 3종

**Files:**
- Modify: `jarvis/tools/jarvis_mcp.py`
- Modify: `tests/tools/test_jarvis_mcp.py`

- [ ] **Step 1: 실패하는 테스트 추가** — test_jarvis_mcp.py 끝에:

```python
def test_set_timer_action_registers_on_board():
    from jarvis.proactive.timers import TimerBoard
    from jarvis.tools.jarvis_mcp import set_timer_action
    board = TimerBoard(clock=lambda: 0.0)
    out = set_timer_action(board, minutes=5, seconds=30, label="라면")
    assert "라면" in out and "5분" in out and "30초" in out
    assert board.listing() == [("라면", 330)]


def test_set_timer_action_rejects_zero():
    from jarvis.proactive.timers import TimerBoard
    from jarvis.tools.jarvis_mcp import set_timer_action
    out = set_timer_action(TimerBoard(), minutes=0, seconds=0, label="")
    assert "몇 분" in out


def test_cancel_and_list_timer_actions():
    from jarvis.proactive.timers import TimerBoard
    from jarvis.tools.jarvis_mcp import cancel_timer_action, list_timers_action
    board = TimerBoard(clock=lambda: 0.0)
    assert "없습니다" in list_timers_action(board)
    board.add(90, "회의")
    assert "회의" in list_timers_action(board) and "1분 30초" in list_timers_action(board)
    assert "취소" in cancel_timer_action(board, "회의")


def test_timer_tools_registered():
    from jarvis.tools.jarvis_mcp import JARVIS_TOOL_NAMES
    for n in ("set_timer", "cancel_timer", "list_timers"):
        assert f"mcp__jarvis__{n}" in JARVIS_TOOL_NAMES
```

- [ ] **Step 2: 실패 확인** — ImportError set_timer_action
- [ ] **Step 3: 구현** — jarvis_mcp.py:

import 블록에 `from ..proactive.timers import DEFAULT_BOARD` 추가.

액션 함수(모듈 레벨, battery_action 근처):

```python
def set_timer_action(board, minutes=0, seconds=0, label: str = "") -> str:
    try:
        total = float(minutes or 0) * 60 + float(seconds or 0)
    except (TypeError, ValueError):
        return "몇 분짜리 타이머인지 말씀해 주세요."
    if total <= 0:
        return "몇 분짜리 타이머인지 말씀해 주세요."
    _tid, lb = board.add(total, label)
    m, s = int(total) // 60, int(total) % 60
    dur = (f"{m}분 " if m else "") + (f"{s}초" if s else "")
    return f"'{lb}' 타이머 {dur.strip()} 시작했습니다. 완료되면 알려드리겠습니다."


def cancel_timer_action(board, label: str = "") -> str:
    return board.cancel(label)


def list_timers_action(board) -> str:
    items = board.listing()
    if not items:
        return "진행 중인 타이머가 없습니다."
    return " / ".join(f"{lb}: {s // 60}분 {s % 60}초 남음" for lb, s in items)
```

@tool 래퍼(모듈 레벨, `_battery` 근처 — DEFAULT_BOARD 사용):

```python
@tool("set_timer", "타이머를 맞춘다(분/초/라벨). 완료되면 자비스가 음성으로 알린다.",
      {"type": "object", "properties": {"minutes": {"type": "number"},
       "seconds": {"type": "number"}, "label": {"type": "string"}}})
async def _set_timer(args):
    a = args or {}
    return _text(set_timer_action(DEFAULT_BOARD, a.get("minutes"), a.get("seconds"),
                                  str(a.get("label") or "")))


@tool("cancel_timer", "진행 중인 타이머를 취소한다.",
      {"type": "object", "properties": {"label": {"type": "string"}}})
async def _cancel_timer(args):
    return _text(cancel_timer_action(DEFAULT_BOARD, str((args or {}).get("label") or "")))


@tool("list_timers", "진행 중인 타이머 목록과 남은 시간을 알려준다.", {})
async def _list_timers(_args):
    return _text(list_timers_action(DEFAULT_BOARD))
```

`build_jarvis_mcp_server`의 tools 리스트에 `_set_timer, _cancel_timer, _list_timers` 추가. `JARVIS_TOOL_NAMES` 튜플에 `"set_timer", "cancel_timer", "list_timers"` 추가.

- [ ] **Step 4: 통과 확인** — test_jarvis_mcp.py 전체 PASS
- [ ] **Step 5: Commit** — `feat(tools): 타이머 도구 3종(set/cancel/list)` (+푸터)

---

### Task 5: system_toggle

**Files:**
- Modify: `jarvis/tools/jarvis_mcp.py`
- Modify: `tests/tools/test_jarvis_mcp.py`

- [ ] **Step 1: 실패하는 테스트 추가**

```python
def _recording_runner(stdout="", returncode=0):
    from types import SimpleNamespace
    calls = []

    def runner(cmd, capture_output=True, text=True, timeout=None, input=None):
        calls.append(cmd)
        return SimpleNamespace(stdout=stdout, returncode=returncode)

    runner.calls = calls
    return runner


def test_toggle_dark_mode():
    from jarvis.tools.jarvis_mcp import system_toggle_action
    r = _recording_runner()
    out = system_toggle_action("dark_mode", "toggle", runner=r)
    assert "다크" in out
    assert any("dark mode" in " ".join(c) for c in r.calls)


def test_toggle_wifi_resolves_device():
    from jarvis.tools.jarvis_mcp import system_toggle_action
    ports = "Hardware Port: Wi-Fi\nDevice: en1\nEthernet Address: aa\n"
    r = _recording_runner(stdout=ports)
    out = system_toggle_action("wifi", "off", runner=r)
    assert "껐" in out
    assert ["networksetup", "-setairportpower", "en1", "off"] in r.calls


def test_toggle_wifi_needs_explicit_state():
    from jarvis.tools.jarvis_mcp import system_toggle_action
    out = system_toggle_action("wifi", "toggle", runner=_recording_runner())
    assert "켜기" in out or "끄기" in out          # 모호한 토글은 거부


def test_toggle_bluetooth_missing_blueutil():
    from jarvis.tools.jarvis_mcp import system_toggle_action

    def no_blueutil(cmd, capture_output=True, text=True, timeout=None, input=None):
        raise FileNotFoundError("blueutil")

    out = system_toggle_action("bluetooth", "on", runner=no_blueutil)
    assert "blueutil" in out                       # 설치 안내


def test_toggle_brightness_presses_key_4x():
    from jarvis.tools.jarvis_mcp import system_toggle_action
    r = _recording_runner()
    system_toggle_action("brightness_up", "on", runner=r)
    assert len([c for c in r.calls if "key code 144" in " ".join(c)]) == 4


def test_toggle_sleep_and_display_off():
    from jarvis.tools.jarvis_mcp import system_toggle_action
    r = _recording_runner()
    assert "절전" in system_toggle_action("sleep", "on", runner=r)
    assert ["pmset", "sleepnow"] in r.calls
    r2 = _recording_runner()
    assert "화면" in system_toggle_action("display_off", "on", runner=r2)
    assert ["pmset", "displaysleepnow"] in r2.calls


def test_toggle_unknown_target_lists_supported():
    from jarvis.tools.jarvis_mcp import system_toggle_action
    out = system_toggle_action("프린터", "on", runner=_recording_runner())
    assert "다크모드" in out
```

- [ ] **Step 2: 실패 확인** — ImportError
- [ ] **Step 3: 구현** — jarvis_mcp.py에:

```python
_BRIGHT_KEYS = {"brightness_up": 144, "brightness_down": 145}
_ON_WORDS = ("on", "true", "1", "켜", "켜줘", "켜기")
_OFF_WORDS = ("off", "false", "0", "꺼", "꺼줘", "끄기")


def _wifi_device(runner=subprocess.run) -> str:
    """Wi-Fi 인터페이스명 탐지 — 기기마다 en0이 아닐 수 있다(USB 어댑터 등)."""
    res = runner(["networksetup", "-listallhardwareports"], capture_output=True,
                 text=True, timeout=10)
    take_next = False
    for line in (getattr(res, "stdout", "") or "").splitlines():
        if "Wi-Fi" in line or "AirPort" in line:
            take_next = True
        elif take_next and line.startswith("Device:"):
            return line.split(":", 1)[1].strip()
    return "en0"


def system_toggle_action(target: str, state: str = "toggle", runner=subprocess.run) -> str:
    target = (target or "").strip().lower()
    state = (state or "toggle").strip().lower()
    on = any(w in state for w in _ON_WORDS)
    off = any(w in state for w in _OFF_WORDS)
    try:
        if target in ("dark_mode", "darkmode", "다크모드"):
            value = "not dark mode" if not (on or off) else ("true" if on else "false")
            _osa("tell application \"System Events\" to tell appearance preferences "
                 f"to set dark mode to {value}", runner)
            word = "전환했" if not (on or off) else ("켰" if on else "껐")
            return f"다크 모드를 {word}습니다."
        if target in ("wifi", "wi-fi", "와이파이"):
            if not (on or off):
                return "와이파이는 켜기/끄기로 말씀해 주세요."
            dev = _wifi_device(runner)
            runner(["networksetup", "-setairportpower", dev, "on" if on else "off"],
                   capture_output=True, text=True, timeout=10)
            return f"와이파이를 {'켰' if on else '껐'}습니다."
        if target in ("bluetooth", "블루투스"):
            if not (on or off):
                return "블루투스는 켜기/끄기로 말씀해 주세요."
            runner(["blueutil", "-p", "1" if on else "0"],
                   capture_output=True, text=True, timeout=10)
            return f"블루투스를 {'켰' if on else '껐'}습니다."
        if target in _BRIGHT_KEYS:
            for _ in range(4):  # 호출당 4단계(약 25%) — 더 원하면 다시 부탁받는다
                _osa(f'tell application "System Events" to key code {_BRIGHT_KEYS[target]}',
                     runner)
            return "밝기를 조절했습니다."
        if target in ("display_off", "화면끄기"):
            runner(["pmset", "displaysleepnow"], capture_output=True, text=True, timeout=10)
            return "화면을 껐습니다."
        if target == "sleep" or "절전" in target:
            runner(["pmset", "sleepnow"], capture_output=True, text=True, timeout=10)
            return "절전 모드로 들어갑니다, 주인님."
    except FileNotFoundError as exc:
        return (f"{exc.args[0] if exc.args else '필요한 명령'}이 설치되어 있지 않습니다. "
                "블루투스 제어는 'brew install blueutil'이 필요합니다.")
    except Exception:  # noqa: BLE001 - 도구는 절대 raise하지 않는다(두뇌가 말로 전달)
        return "시스템 설정 변경에 실패했습니다."
    return ("지원하는 항목: 다크모드, 와이파이, 블루투스, 밝기(brightness_up/down), "
            "화면끄기(display_off), 절전(sleep). 방해금지는 단축어 앱에서 만들어 "
            "run_shortcut으로 실행할 수 있습니다.")
```

@tool 래퍼:

```python
@tool("system_toggle",
      "맥 시스템 설정 전환: dark_mode/wifi/bluetooth/brightness_up/brightness_down/"
      "display_off/sleep. state는 on/off/toggle. 방해금지(DND)는 직접 지원하지 않음 — "
      "사용자가 단축어를 만들면 run_shortcut으로 가능하다고 안내하라.",
      {"type": "object", "properties": {"target": {"type": "string"},
       "state": {"type": "string"}}, "required": ["target"]})
async def _system_toggle(args):
    a = args or {}
    return _text(system_toggle_action(str(a.get("target", "")), str(a.get("state", "toggle"))))
```

tools 리스트 + JARVIS_TOOL_NAMES에 `"system_toggle"` 등록.

주의: `FileNotFoundError` 분기가 동작하려면 blueutil 호출이 try 안에 있어야 한다(위 코드 그대로). 테스트의 fake runner는 `input=` 키워드도 받는다(클립보드 Task 6과 공유).

- [ ] **Step 4: 통과 확인** — 7 PASS + 기존 전체
- [ ] **Step 5: Commit** — `feat(tools): system_toggle — 다크모드/와이파이/블루투스/밝기/화면/절전` (+푸터)

---

### Task 6: 클립보드 + 단축어

**Files:**
- Modify: `jarvis/tools/jarvis_mcp.py`
- Modify: `tests/tools/test_jarvis_mcp.py`

- [ ] **Step 1: 실패하는 테스트 추가** (Task 5의 `_recording_runner` 재사용)

```python
def test_clipboard_read_truncates():
    from jarvis.tools.jarvis_mcp import clipboard_read_action
    r = _recording_runner(stdout="x" * 5000)
    out = clipboard_read_action(runner=r)
    assert "생략" in out and len(out) < 4200
    assert ["pbpaste"] in r.calls


def test_clipboard_read_empty():
    from jarvis.tools.jarvis_mcp import clipboard_read_action
    assert "비어" in clipboard_read_action(runner=_recording_runner(stdout=""))


def test_clipboard_write_pipes_text():
    from jarvis.tools.jarvis_mcp import clipboard_write_action
    captured = {}

    def runner(cmd, capture_output=True, text=True, timeout=None, input=None):
        from types import SimpleNamespace
        captured["cmd"], captured["input"] = cmd, input
        return SimpleNamespace(stdout="", returncode=0)

    out = clipboard_write_action("안녕하세요", runner=runner)
    assert "복사" in out
    assert captured["cmd"] == ["pbcopy"] and captured["input"] == "안녕하세요"


def test_run_shortcut_success_and_failure():
    from jarvis.tools.jarvis_mcp import run_shortcut_action
    ok = _recording_runner(stdout="결과물")
    out = run_shortcut_action("퇴근", runner=ok)
    assert "퇴근" in out and "결과물" in out
    fail = _recording_runner(stdout="이름1\n이름2", returncode=1)
    out = run_shortcut_action("없는것", runner=fail)
    assert "실패" in out


def test_list_shortcuts():
    from jarvis.tools.jarvis_mcp import list_shortcuts_action
    r = _recording_runner(stdout="퇴근\n방해금지\n")
    out = list_shortcuts_action(runner=r)
    assert "2개" in out and "퇴근" in out
```

- [ ] **Step 2: 실패 확인** — ImportError
- [ ] **Step 3: 구현**

```python
def clipboard_read_action(runner=subprocess.run) -> str:
    res = runner(["pbpaste"], capture_output=True, text=True, timeout=10)
    out = (getattr(res, "stdout", "") or "").strip()
    if not out:
        return "클립보드가 비어 있습니다."
    if len(out) > 4000:  # 두뇌 컨텍스트 보호 — 긴 본문은 잘라서
        out = out[:4000] + " …(이하 생략)"
    return f"클립보드 내용: {out}"


def clipboard_write_action(text: str, runner=subprocess.run) -> str:
    if not (text or "").strip():
        return "복사할 내용을 말씀해 주세요."
    runner(["pbcopy"], capture_output=True, text=True, timeout=10, input=text)
    return "클립보드에 복사했습니다."


def run_shortcut_action(name: str, runner=subprocess.run) -> str:
    name = (name or "").strip()
    if not name:
        return "어느 단축어를 실행할까요?"
    try:
        res = runner(["shortcuts", "run", name], capture_output=True, text=True, timeout=30)
    except Exception:  # noqa: BLE001 - 타임아웃 포함: 실행은 백그라운드에서 계속된다
        return f"'{name}' 단축어가 30초 안에 끝나지 않았습니다 — 백그라운드에서 계속됩니다."
    if getattr(res, "returncode", 1) != 0:
        return f"'{name}' 단축어 실행에 실패했습니다. list_shortcuts로 정확한 이름을 확인하세요."
    out = (getattr(res, "stdout", "") or "").strip()
    return f"'{name}' 단축어를 실행했습니다." + (f" 결과: {out[:500]}" if out else "")


def list_shortcuts_action(runner=subprocess.run) -> str:
    res = runner(["shortcuts", "list"], capture_output=True, text=True, timeout=15)
    names = [ln.strip() for ln in (getattr(res, "stdout", "") or "").splitlines() if ln.strip()]
    if not names:
        return "만들어 둔 단축어가 없습니다."
    head = ", ".join(names[:20])
    more = f" 외 {len(names) - 20}개" if len(names) > 20 else ""
    return f"단축어 {len(names)}개: {head}{more}"
```

@tool 래퍼 4개(설명에 한계 명시):

```python
@tool("clipboard_read", "클립보드의 텍스트를 읽는다(요약·낭독용).", {})
async def _clipboard_read(_args):
    return _text(clipboard_read_action())


@tool("clipboard_write", "텍스트를 클립보드에 복사한다.",
      {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]})
async def _clipboard_write(args):
    return _text(clipboard_write_action(str((args or {}).get("text", ""))))


@tool("run_shortcut", "macOS 단축어(Shortcuts) 앱의 단축어를 이름으로 실행한다. "
      "방해금지·스마트홈 등 확장은 사용자가 단축어를 만들면 전부 가능.",
      {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]})
async def _run_shortcut(args):
    return _text(run_shortcut_action(str((args or {}).get("name", ""))))


@tool("list_shortcuts", "사용 가능한 macOS 단축어 목록.", {})
async def _list_shortcuts(_args):
    return _text(list_shortcuts_action())
```

tools 리스트 + JARVIS_TOOL_NAMES에 `"clipboard_read", "clipboard_write", "run_shortcut", "list_shortcuts"` 등록.

- [ ] **Step 4: 통과 확인** — 5 PASS + 전체
- [ ] **Step 5: Commit** — `feat(tools): 클립보드 읽기/쓰기 + 단축어 실행/목록` (+푸터)

---

### Task 7: play_music

**Files:**
- Modify: `jarvis/tools/jarvis_mcp.py`
- Modify: `tests/tools/test_jarvis_mcp.py`

- [ ] **Step 1: 실패하는 테스트 추가**

```python
def test_play_music_track_success():
    from types import SimpleNamespace
    from jarvis.tools.jarvis_mcp import play_music_action
    calls = []

    def runner(cmd, capture_output=True, text=True, timeout=None, input=None):
        calls.append(cmd)
        script = cmd[-1]
        if "first track" in script:
            return SimpleNamespace(stdout="", returncode=0)
        return SimpleNamespace(stdout="Money Trees — Kendrick Lamar", returncode=0)

    out = play_music_action("머니 트리", kind="track", runner=runner)
    assert "재생" in out


def test_play_music_any_falls_through_and_fails():
    from types import SimpleNamespace
    from jarvis.tools.jarvis_mcp import play_music_action

    def runner(cmd, capture_output=True, text=True, timeout=None, input=None):
        return SimpleNamespace(stdout="", returncode=1)

    out = play_music_action("없는곡", runner=runner)
    assert "찾지 못했습니다" in out and "카탈로그" in out


def test_play_music_escapes_quotes():
    from types import SimpleNamespace
    from jarvis.tools.jarvis_mcp import play_music_action
    seen = []

    def runner(cmd, capture_output=True, text=True, timeout=None, input=None):
        seen.append(cmd[-1])
        return SimpleNamespace(stdout="", returncode=0)

    play_music_action('악"곡', kind="track", runner=runner)
    assert '\\"' in seen[0]                        # 따옴표 이스케이프


def test_play_music_registered():
    from jarvis.tools.jarvis_mcp import JARVIS_TOOL_NAMES
    assert "mcp__jarvis__play_music" in JARVIS_TOOL_NAMES
```

- [ ] **Step 2: 실패 확인** — ImportError
- [ ] **Step 3: 구현**

```python
_MUSIC_FIND = {
    "track": 'play (first track of library playlist 1 whose name contains "{q}")',
    "artist": 'play (first track of library playlist 1 whose artist contains "{q}")',
    "album": 'play (first track of library playlist 1 whose album contains "{q}")',
    "playlist": 'play (first user playlist whose name contains "{q}")',
}


def play_music_action(query: str, kind: str = "any", runner=subprocess.run) -> str:
    q = (query or "").strip().replace('"', '\\"')
    if not q:
        return "무엇을 틀까요?"
    order = [kind] if kind in _MUSIC_FIND else ["track", "artist", "playlist"]
    for k in order:
        body = _MUSIC_FIND[k].replace("{q}", q)
        res = runner(["osascript", "-e", f'tell application "Music" to {body}'],
                     capture_output=True, text=True, timeout=15)
        if getattr(res, "returncode", 1) == 0:
            now = _osa('tell application "Music" to if player state is playing then '
                       'return (name of current track) & " — " & (artist of current track)',
                       runner)
            return f"재생합니다: {now}" if now else "재생을 시작했습니다."
    return (f"라이브러리에서 '{query}'를 찾지 못했습니다. "
            "(애플뮤직 카탈로그 검색은 지원하지 않습니다 — 라이브러리에 있는 것만)")
```

@tool 래퍼:

```python
@tool("play_music", "음악 라이브러리에서 곡/아티스트/플레이리스트를 찾아 재생한다. "
      "kind: track|artist|album|playlist|any. 라이브러리 한정(카탈로그 검색 불가).",
      {"type": "object", "properties": {"query": {"type": "string"},
       "kind": {"type": "string"}}, "required": ["query"]})
async def _play_music(args):
    a = args or {}
    return _text(play_music_action(str(a.get("query", "")), str(a.get("kind", "any"))))
```

tools 리스트 + JARVIS_TOOL_NAMES에 `"play_music"` 등록.

- [ ] **Step 4: 통과 확인** — 4 PASS + 전체
- [ ] **Step 5: Commit** — `feat(tools): play_music — 라이브러리 지정 재생` (+푸터)

---

### Task 8: 배선 — DEFAULT_BOARD + cooldown_overrides

**Files:**
- Modify: `jarvis/__main__.py`
- Modify: `tests/test_main_wiring.py`

- [ ] **Step 1: 실패하는 테스트 추가** — test_main_wiring.py 끝에:

```python
def test_build_orchestrator_wires_timer_monitor():
    orch = _build()
    names = [type(m).__name__ for m in orch.proactive._monitors]
    assert "TimerMonitor" in names
    # 타이머는 연속 알림이 정상 — 쿨다운 면제 확인
    assert orch.proactive._cooldown_overrides.get("timer_done") == 0.0
```

- [ ] **Step 2: 실패 확인** — TimerMonitor not in names
- [ ] **Step 3: 구현** — __main__.py:

import에 `from .proactive.timers import DEFAULT_BOARD` 추가. `build_orchestrator`의 ProactiveEngine 구성을:

```python
        orch.proactive = ProactiveEngine(
            build_monitors(settings, timers=DEFAULT_BOARD),
            announce=orch.announce,
            can_speak=orch._can_announce,
            cooldown_s=settings.proactive_cooldown_min * 60,
            cooldown_overrides={"timer_done": 0.0},  # 연속 타이머는 정상 동작
        )
```

- [ ] **Step 4: 통과 확인** — test_main_wiring.py 전체 + 풀 스위트 PASS, ruff clean
- [ ] **Step 5: Commit** — `feat(proactive): 타이머 보드 배선 — 도구·감시자 공유 + 쿨다운 면제` (+푸터)

---

### Task 9: 풀 Claude Code 능력 개방 + 음성 확인 게이트

사용자 요구: "이 능력들만 되게 설정하지 말고 클로드 코드로 할 수 있는 건 다 되게". 두뇌가 Bash·파일 읽기/쓰기/수정·Glob/Grep 등 전체 도구를 쓰되, 파괴적 도구는 음성으로 확인받는다. claude-agent-sdk 0.2.x의 `can_use_tool` 콜백(`async (tool_name, input, ToolPermissionContext) -> PermissionResultAllow|PermissionResultDeny`)에 기존 `VoiceConfirm.confirm(prompt)->bool`을 연결한다.

**Files:**
- Modify: `jarvis/brain/subscription.py`
- Modify: `jarvis/brain/factory.py`
- Create: `tests/brain/test_can_use_tool.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/brain/test_can_use_tool.py
import asyncio

from jarvis.brain.subscription import SubscriptionBrain
from jarvis.core.config import Settings


def _brain(confirm=None):
    return SubscriptionBrain(Settings(), None, "p" * 4096, confirm=confirm)


def _ctx():
    from claude_agent_sdk import ToolPermissionContext
    return ToolPermissionContext(tool_use_id="t1")


def _decide(brain, tool, inp):
    return asyncio.run(brain._can_use_tool(tool, inp, _ctx()))


def test_readonly_tools_auto_allowed():
    brain = _brain(confirm=None)              # confirm 없어도 읽기셋은 허용
    for tool in ("Read", "Glob", "Grep", "TodoWrite", "WebSearch", "WebFetch"):
        assert _decide(brain, tool, {}).behavior == "allow"


def test_destructive_tool_denied_without_confirm():
    brain = _brain(confirm=None)              # confirm 미주입 → 차단이 기본
    assert _decide(brain, "Bash", {"command": "rm -rf x"}).behavior == "deny"
    assert _decide(brain, "Write", {"file_path": "/x"}).behavior == "deny"


def test_destructive_tool_allowed_on_yes():
    asked = []

    async def confirm(prompt):
        asked.append(prompt)
        return True

    brain = _brain(confirm=confirm)
    res = _decide(brain, "Bash", {"command": "ls ~/Desktop"})
    assert res.behavior == "allow"
    assert "ls ~/Desktop" in asked[0]         # 명령이 음성 프롬프트에 들어간다


def test_destructive_tool_denied_on_no():
    async def confirm(prompt):
        return False

    brain = _brain(confirm=confirm)
    res = _decide(brain, "Write", {"file_path": "/Users/x/note.txt"})
    assert res.behavior == "deny"
    assert "note.txt" in res.message or "취소" in res.message


def test_factory_injects_confirm():
    from jarvis.brain.factory import make_brain
    calls = []

    async def confirm(prompt):
        calls.append(prompt)
        return True

    brain = make_brain(Settings(), None, "p" * 4096, confirm=confirm)
    asyncio.run(brain._can_use_tool("Bash", {"command": "echo hi"}, _ctx()))
    assert calls                              # 주입된 confirm이 실제로 호출됨
```

- [ ] **Step 2: 실패 확인** — `.venv/bin/python -m pytest tests/brain/test_can_use_tool.py -v` → AttributeError `_can_use_tool` / TypeError confirm

- [ ] **Step 3: 구현**

3a. subscription.py — `__init__` 시그니처에 `confirm: Any = None`을 키워드 인자로 추가(`stream_event` 뒤), 본문에 `self._confirm = confirm` 저장.

3b. subscription.py 상단 클래스 영역에 안전셋 상수 + 콜백 추가:

```python
    # 읽기 전용·무해 — 음성 확인 없이 자동 허용.
    _SAFE_TOOLS = frozenset({"Read", "Glob", "Grep", "TodoWrite", "WebSearch",
                             "WebFetch", "NotebookRead"})

    def _confirm_prompt(self, tool: str, inp: dict) -> str:
        if tool == "Bash":
            cmd = str(inp.get("command", ""))[:80]
            return f"명령을 실행할까요? {cmd}"
        if tool in ("Write", "Edit", "NotebookEdit"):
            path = inp.get("file_path") or inp.get("notebook_path") or "파일"
            return f"{path} 파일을 수정할까요?"
        return f"{tool} 작업을 실행할까요?"

    async def _can_use_tool(self, tool_name, tool_input, context):
        from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

        base = tool_name.split("__")[-1]  # mcp__jarvis__x → x
        if tool_name in self._SAFE_TOOLS or base in self._SAFE_TOOLS \
                or tool_name.startswith("mcp__jarvis__"):
            return PermissionResultAllow()
        if self._confirm is None:
            # 확인 수단이 없으면 파괴적 도구는 막는다(잘못 들은 음성이 rm 실행 금지).
            return PermissionResultDeny(message=f"{base}은 음성 확인이 필요합니다.")
        ok = await self._confirm(self._confirm_prompt(base, dict(tool_input or {})))
        if ok:
            return PermissionResultAllow()
        return PermissionResultDeny(message=f"{base} 작업을 취소했습니다.")
```

3c. subscription.py `_options()` — 전체 도구 개방으로 교체:

```python
        from pathlib import Path

        from jarvis.tools.jarvis_mcp import JARVIS_TOOL_NAMES, build_jarvis_mcp_server
        kw: dict[str, Any] = dict(
            system_prompt=self._system_prompt(),
            # 전체 도구 사용 가능 — 읽기셋은 자동, Bash/파일수정은 _can_use_tool이
            # 음성으로 확인. allowed_tools는 '확인 없이 바로'인 자동 허용 목록.
            allowed_tools=["WebSearch", "WebFetch", "Read", "Glob", "Grep",
                           "TodoWrite", *JARVIS_TOOL_NAMES],
            can_use_tool=self._can_use_tool,
            mcp_servers={"jarvis": build_jarvis_mcp_server(self._memory)},
            setting_sources=[],    # isolate from the host Claude Code project
            cwd=str(Path.home()),  # 파일 작업 기준 디렉터리 = 홈
            max_turns=20,          # 멀티스텝 작업(파일 만들고 확인 등) 헤드룸
            max_thinking_tokens=thinking_tokens,
            env=env,
            include_partial_messages=True,
        )
```

(`disallowed_tools` 줄은 삭제 — 이제 게이트가 막는다. 기존 주석도 갱신.)

3d. subscription.py 지침(_GUIDANCE_EN, [SYSTEM EVENT] 문장 근처)에 한 문장 추가:

```python
    "You have full tool access (bash, file read/write/edit, search); destructive "
    "steps are voice-confirmed by the system, so just use them when needed. Prefer "
    "the dedicated jarvis tools for simple actions (volume, music, timers) over bash. "
```

3e. factory.py — subscription 분기에서 confirm 전달:

```python
    if backend == "subscription":
        from jarvis.brain.subscription import SubscriptionBrain
        return SubscriptionBrain(settings, memory, persona_text, confirm=confirm)
```

- [ ] **Step 4: 통과 확인** — `tests/brain/test_can_use_tool.py` 5 PASS + `tests/brain/` 전체 + `tests/test_main_wiring.py`(confirm 주입 경로) PASS, ruff clean
- [ ] **Step 5: Commit** — `feat(brain): 풀 도구 개방 + 음성 확인 게이트(can_use_tool)` (+푸터)

---

### Task 10: 전체 검증 (라이브는 컨트롤러)

- [ ] **Step 1:** `.venv/bin/python -m pytest -q` 전체 PASS, `.venv/bin/ruff check jarvis tests` clean
- [ ] **Step 2 (컨트롤러):** 재시작 후 라이브 체크: ① "10초 타이머" → 완료 음성 알림 ② "다크모드 토글" ③ "클립보드 읽어줘" ④ "단축어 목록" ⑤ "음악에서 ~ 틀어줘" ⑥ 타이머 2개 연달아 → 둘 다 알림 ⑦ "바탕화면에 메모 파일 만들어줘" → Write 음성 확인 후 생성 ⑧ "다운로드 폴더에 뭐 있어?" → Bash 음성 확인 또는 Glob 자동
- [ ] **Step 3 (컨트롤러):** 메모리 업데이트

## 셀프리뷰 결과

- **스펙 커버리지**: 타이머(T1 보드/T3 모니터/T4 도구/T8 배선+쿨다운 면제, ttl 120·prio 1·1초 폴링) ✓ / system_toggle 6종+wifi 장치 탐지+blueutil 안내+DND 우회 문구(T5) ✓ / 클립보드 4000자 컷(T6) ✓ / 단축어 30s 타임아웃+실패 안내(T6) ✓ / play_music 라이브러리 한정 명시+이스케이프(T7) ✓ / 도구 raise 금지(전부 안내 문자열) ✓ / 설정 추가 없음 ✓.
- **타입 일치**: `TimerBoard.add(seconds, label) -> (id, label)` T1↔T4 / `cancel(label)->str`·`listing()->[(라벨,초)]`·`pop_due()->[라벨]` T1↔T3·T4 / `build_monitors(settings, timers=None)` T3↔T8 / `cooldown_overrides` T2↔T8 / `_recording_runner(... input=None)` 시그니처 T5↔T6 공유 ✓. `can_use_tool(tool_name, input, ctx)->PermissionResultAllow|Deny`(SDK 0.2.x 실측) T9 / `confirm(prompt)->bool` 기존 VoiceConfirm 시그니처 재사용 ✓.
- **풀 능력(F)**: T9가 can_use_tool로 전체 도구 개방 + 읽기셋 자동·파괴셋 음성확인·confirm 미주입 시 차단, factory confirm 주입, 지침 1문장, cwd=홈, max_turns 20 ✓.
- **플레이스홀더 없음**: 전 스텝 완결 코드.
