# JARVIS Phase 1 · M3 — Tools + MCP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 비서가 작업을 실행: 게이팅된 수동 tool-use 루프(작업 경로=Opus) + 키워드 라우터 + 스타터 도구(시간/날씨/웹검색) + 확장 가능한 MCP 슬롯.

**Architecture:** 작업 경로는 claude-opus-4-8 + adaptive thinking + effort high의 수동 게이팅 루프(되돌릴 수 없는 도구는 음성 확인). ToolRegistry + MCP stdio 클라이언트(AsyncExitStack), premiere-pro는 Phase2용 비활성 스텁.

**Tech Stack:** anthropic beta_tool, web_search_20260209(server-side), mcp==1.27.1, tool_search_tool_bm25_20251119

**Spec:** `docs/superpowers/specs/2026-06-09-jarvis-voice-assistant-design.md`

---

I have confirmed the exact signatures against the `claude-api` reference and `anthropic==0.107.1`: `from anthropic import beta_async_tool` decorated objects expose `.name`/`.to_dict()`/`.call(input)` (dispatch awaits `.call`); `from anthropic.lib.tools.mcp import async_mcp_tool` with `async_mcp_tool(tool, session, *, defer_loading=...)`; the server-side web tool type is `web_search_20260209` and the deferred-loading search tool type is `tool_search_tool_bm25_20251119`; the async streaming loop is `async with client.messages.stream(...) as stream: async for text in stream.text_stream: ...; final = await stream.get_final_message()`; and the task path uses `thinking={"type":"adaptive"}` + `output_config={"effort":"high"}` on `claude-opus-4-8` (NEVER on the Haiku conversational path — `effort`/`thinking` 400 on Haiku 4.5).

This milestone **extends** the M1 `Brain` additively (it does NOT replace it incompatibly): M1 `Brain(settings, memory, persona_text, client=None)` keeps its positional order and M3 ADDS keyword-only `registry=None, confirm=None`, retaining `async warm()`, `last_usage`, the two-block cached system prompt (persona cached + memory/guidance uncached), and `_GUIDANCE` on BOTH paths. `tests/test_brain.py` (M1) is re-run in the same Brain task and stays green. Here is the milestone plan.

## Milestone 3: Tools + MCP

**Goal:** The JARVIS assistant can DO things — a keyword-routed TASK path drives `claude-opus-4-8` through a manual, voice-gated streaming tool loop over a heterogeneous tool catalog (server-side `web_search` dict + local `@beta_async_tool` builtins incl. `get_time`/`get_weather`/`calc`/`remember` + MCP-wrapped tools), with irreversible actions confirmed by a REAL voice prompt (TTS → PTT → STT → Korean yes/no) before dispatch, and a short `잠시만요` filler spoken before the multi-second Opus turn. `jarvis.__main__.build_orchestrator` wires the whole catalog + confirm into the live PTT→STT→Brain→TTS pipeline.

**Acceptance criteria:**
- [ ] A Korean time question routes to the TASK path, emits the `잠시만요` filler, triggers `get_time`, and yields a spoken (text-delta) Korean answer.
- [ ] A gated (irreversible) tool requests confirmation via the injected real-voice `confirm` callback before dispatch; declining prevents execution and feeds a cancellation `tool_result` back.
- [ ] `"3 더하기 5 알려주고 메모해줘"` routes to TASK, dispatches `calc` (=8) and `remember` (wraps `MemoryStore.remember`) in one turn, and produces a spoken Korean answer — end-to-end.
- [ ] `ToolRegistry` holds heterogeneous tools (server `web_search_20260209` dict + `@beta_async_tool` local + MCP wrapped tool) that coexist in `tools()` with correct `is_gated`/`dispatch` behavior (raw/server dicts are non-local and raise on dispatch).
- [ ] `mcp_client` wires `stdio_client`+`ClientSession` through an `AsyncExitStack`, uses `anthropic.lib.tools.mcp.async_mcp_tool` when importable else a hand-rolled wrapper, supports `defer_loading` + `tool_search_tool_bm25_20251119`, and ships a disabled `premiere-pro` Phase-2 stub.
- [ ] `build_orchestrator` builds the `ToolRegistry`, the real `VoiceConfirm`, the extended `Brain(... registry=, confirm=)`, holds the MCP `AsyncExitStack` open for the process lifetime, and injects everything into the canonical DI `Orchestrator`.
- [ ] `pytest -q` is fully green including the migrated M1 `tests/test_brain.py`; a live-API manual check shows `get_time` dispatched and a Korean time answer spoken.

---

### Task 1: ToolRegistry (register / tools / is_gated / dispatch) + `beta_async_tool` startup import-check

**Files:**
- Create: `~/jarvis/jarvis/tools/__init__.py`
- Create: `~/jarvis/jarvis/tools/registry.py`
- Test: `~/jarvis/tests/tools/test_registry.py`

Steps:

- [ ] **Step 1: Create the empty package marker.** Write `~/jarvis/jarvis/tools/__init__.py` with a single line:
```python
"""JARVIS tool registry, builtins, voice-confirm, and MCP client (Milestone 3)."""
```

- [ ] **Step 2: Write the failing test (full code).** Create `~/jarvis/tests/tools/test_registry.py`:
```python
import asyncio

import pytest
from anthropic import beta_async_tool

from jarvis.tools.registry import ToolRegistry


def test_register_local_tool_lists_and_dispatches():
    @beta_async_tool
    async def echo(text: str) -> str:
        """문자열을 그대로 반환합니다.

        Args:
            text: 반환할 문자열.
        """
        return f"echo:{text}"

    reg = ToolRegistry()
    assert reg.register(echo) is None  # contract: register(...) -> None
    names = [d["name"] for d in reg.tools()]
    assert "echo" in names
    assert reg.is_gated("echo") is False
    assert asyncio.run(reg.dispatch("echo", {"text": "hi"})) == "echo:hi"


def test_gated_registration_marks_name():
    @beta_async_tool
    async def danger(path: str) -> str:
        """대상을 영구 삭제합니다.

        Args:
            path: 삭제할 경로.
        """
        return "done"

    reg = ToolRegistry()
    reg.register(danger, gated=True)
    assert reg.is_gated("danger") is True
    assert asyncio.run(reg.dispatch("danger", {"path": "/x"})) == "done"


def test_raw_dict_is_non_local_and_not_dispatchable():
    reg = ToolRegistry()
    d = {"type": "web_search_20260209", "name": "web_search"}
    reg.register(d)
    assert d in reg.tools()
    assert reg.is_gated("web_search") is False
    with pytest.raises(KeyError):
        asyncio.run(reg.dispatch("web_search", {}))


def test_heterogeneous_tools_coexist():
    @beta_async_tool
    async def get_x() -> str:
        """엑스를 반환합니다."""
        return "x"

    reg = ToolRegistry()
    reg.register(get_x)
    reg.register({"type": "web_search_20260209", "name": "web_search"})
    defs = reg.tools()
    assert len(defs) == 2
    assert {d.get("name") for d in defs} == {"get_x", "web_search"}
```

- [ ] **Step 3: Run & show expected FAIL (genuine red — module + symbol absent).**
```bash
~/jarvis/.venv/bin/python -m pytest tests/tools/test_registry.py -q
```
Expected: `ModuleNotFoundError: No module named 'jarvis.tools.registry'` (collection error, 0 passed) — `jarvis/tools/registry.py` does not exist yet, so `ToolRegistry` is genuinely missing.

- [ ] **Step 4: Minimal implementation (full code).** Create `~/jarvis/jarvis/tools/registry.py`:
```python
from __future__ import annotations

import inspect
from typing import Any

# Startup import-check: local tools are produced by @beta_async_tool, whose
# .call() is awaited in dispatch(). This GUARDS the pinned SDK so a missing or
# wrong-version anthropic fails loudly at import time with a clear message.
try:  # pragma: no cover - environment guard
    from anthropic import beta_async_tool as _beta_async_tool  # noqa: F401
except ImportError as exc:  # pragma: no cover - environment guard
    raise ImportError(
        "jarvis.tools.registry requires `beta_async_tool` from anthropic==0.107.1. "
        "Install the pinned SDK: pip install 'anthropic==0.107.1'."
    ) from exc


class ToolRegistry:
    """Holds heterogeneous tools for the TASK path.

    Local tools are objects produced by ``@beta_async_tool`` (or an MCP
    wrapper): they expose ``.name``, ``.to_dict()`` and ``.call()`` and are
    dispatchable locally. Raw/server-side tools (e.g. the web_search dict) are
    plain dicts: they are listed for the API but NOT dispatchable locally and
    are never gated.
    """

    def __init__(self) -> None:
        self._local: dict[str, Any] = {}
        self._raw: list[dict[str, Any]] = []
        self._gated: set[str] = set()

    def register(self, fn: Any, gated: bool = False) -> None:
        """Register a local tool object or a raw server-tool dict.

        ``gated=True`` marks an irreversible local action that must be
        voice-confirmed before dispatch. ``gated`` is ignored for raw dicts.
        """
        if isinstance(fn, dict):
            self._raw.append(fn)
            return
        if not (hasattr(fn, "to_dict") and hasattr(fn, "call") and hasattr(fn, "name")):
            raise TypeError(
                "register() expects a @beta_async_tool object (or MCP wrapper) "
                "with .name/.to_dict()/.call(), or a raw server-tool dict"
            )
        self._local[fn.name] = fn
        if gated:
            self._gated.add(fn.name)

    def tools(self) -> list[dict[str, Any]]:
        """Tool-definition dicts for messages(...) tools=."""
        out: list[dict[str, Any]] = [t.to_dict() for t in self._local.values()]
        out.extend(self._raw)
        return out

    def is_gated(self, name: str) -> bool:
        return name in self._gated

    async def dispatch(self, name: str, args: Any) -> str:
        """Run a local tool by name; raise KeyError for unknown/non-local."""
        if name not in self._local:
            raise KeyError(name)
        result = self._local[name].call(dict(args) if args else {})
        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, str):
            return result
        # Iterable[BetaContent] -> join any text parts.
        parts: list[str] = []
        for block in result:
            text = getattr(block, "text", None)
            if text is None and isinstance(block, dict):
                text = block.get("text")
            parts.append(text if text is not None else str(block))
        return "\n".join(parts)
```

- [ ] **Step 5: Run & show expected PASS.**
```bash
~/jarvis/.venv/bin/python -m pytest tests/tools/test_registry.py -q
```
Expected: `4 passed`.

- [ ] **Step 6: Commit.**
```bash
git -C ~/jarvis add jarvis/tools/__init__.py jarvis/tools/registry.py tests/tools/test_registry.py
git -C ~/jarvis commit -m "M3 Task1: ToolRegistry register/tools/is_gated/dispatch + beta_async_tool import-check"
```

---

### Task 2: Local builtins — get_time / get_weather (`@beta_async_tool`)

**Files:**
- Create: `~/jarvis/jarvis/tools/builtin/__init__.py`
- Create: `~/jarvis/jarvis/tools/builtin/time_weather.py`
- Test: `~/jarvis/tests/tools/test_time_weather.py`

Steps:

- [ ] **Step 1: Create the builtin package marker.** Write `~/jarvis/jarvis/tools/builtin/__init__.py`:
```python
"""Local @beta_async_tool builtins for JARVIS."""
```

- [ ] **Step 2: Write the failing test (full code).** Create `~/jarvis/tests/tools/test_time_weather.py`:
```python
import asyncio
import re

import jarvis.tools.builtin.time_weather as tw
from jarvis.tools.builtin.time_weather import get_time, get_weather


def test_get_time_returns_korean_kst_string():
    out = asyncio.run(get_time.call({}))
    assert re.match(
        r"\d{4}년 \d{1,2}월 \d{1,2}일 [월화수목금토일]요일 \d{1,2}시 \d{1,2}분입니다\.",
        out,
    )


def test_get_weather_formats_korean_offline(monkeypatch):
    async def fake_fetch(latitude, longitude):
        assert (round(latitude, 3), round(longitude, 3)) == (35.180, 129.076)
        return {"temperature_2m": 21.4, "weather_code": 61}

    monkeypatch.setattr(tw, "_fetch_current", fake_fetch)
    out = asyncio.run(get_weather.call({"city": "부산"}))
    assert "부산" in out
    assert "약한 비" in out
    assert "21.4" in out


def test_get_weather_defaults_to_seoul(monkeypatch):
    async def fake_fetch(latitude, longitude):
        assert round(latitude, 3) == 37.566
        return {"temperature_2m": 3.0, "weather_code": 0}

    monkeypatch.setattr(tw, "_fetch_current", fake_fetch)
    out = asyncio.run(get_weather.call({}))
    assert "서울" in out and "맑음" in out
```

- [ ] **Step 3: Run & show expected FAIL (genuine red — module absent).**
```bash
~/jarvis/.venv/bin/python -m pytest tests/tools/test_time_weather.py -q
```
Expected: `ModuleNotFoundError: No module named 'jarvis.tools.builtin.time_weather'`.

- [ ] **Step 4: Minimal implementation (full code).** Create `~/jarvis/jarvis/tools/builtin/time_weather.py` (`httpx` ships with the `anthropic` dependency, so no new pin):
```python
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from anthropic import beta_async_tool

_CITY_COORDS: dict[str, tuple[float, float]] = {
    "서울": (37.5665, 126.9780),
    "부산": (35.1796, 129.0756),
    "인천": (37.4563, 126.7052),
    "대구": (35.8714, 128.6014),
    "대전": (36.3504, 127.3845),
    "광주": (35.1595, 126.8526),
}

_WMO: dict[int, str] = {
    0: "맑음", 1: "대체로 맑음", 2: "구름 조금", 3: "흐림",
    45: "안개", 48: "서리 안개",
    51: "약한 이슬비", 53: "이슬비", 55: "강한 이슬비",
    61: "약한 비", 63: "비", 65: "강한 비",
    71: "약한 눈", 73: "눈", 75: "강한 눈",
    80: "소나기", 81: "강한 소나기", 95: "천둥번개",
}


async def _fetch_current(latitude: float, longitude: float) -> dict:
    """Fetch Open-Meteo current weather (no API key). Patched out in tests."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": latitude,
                "longitude": longitude,
                "current": "temperature_2m,weather_code",
                "timezone": "auto",
            },
        )
        resp.raise_for_status()
        return resp.json()["current"]


@beta_async_tool
async def get_time() -> str:
    """현재 한국 표준시(KST)의 날짜와 시간을 조회합니다."""
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    days = ["월", "화", "수", "목", "금", "토", "일"]
    return (
        f"{now.year}년 {now.month}월 {now.day}일 "
        f"{days[now.weekday()]}요일 {now.hour}시 {now.minute}분입니다."
    )


@beta_async_tool
async def get_weather(city: str = "서울") -> str:
    """한국 도시의 현재 날씨를 조회합니다.

    Args:
        city: 날씨를 조회할 한국 도시 이름 (예: 서울, 부산). 기본값은 서울입니다.
    """
    latitude, longitude = _CITY_COORDS.get(city, _CITY_COORDS["서울"])
    current = await _fetch_current(latitude, longitude)
    desc = _WMO.get(int(current.get("weather_code", 0)), "알 수 없음")
    temp = current.get("temperature_2m")
    return f"{city}의 현재 날씨는 {desc}, 기온은 섭씨 {temp}도입니다."
```

- [ ] **Step 5: Run & show expected PASS.**
```bash
~/jarvis/.venv/bin/python -m pytest tests/tools/test_time_weather.py -q
```
Expected: `3 passed`.

- [ ] **Step 6: Commit.**
```bash
git -C ~/jarvis add jarvis/tools/builtin/__init__.py jarvis/tools/builtin/time_weather.py tests/tools/test_time_weather.py
git -C ~/jarvis commit -m "M3 Task2: local builtins get_time/get_weather (@beta_async_tool)"
```

---

### Task 3: Local builtins — `calc` + `remember` (wraps `MemoryStore.remember`)

The spec acceptance `"3 더하기 5 알려주고 메모해줘"` needs a local arithmetic tool and a note-taking tool. `calc` is a stateless module-level `@beta_async_tool` with a SAFE AST evaluator (no `eval`). `remember` needs the live `MemoryStore`, so it is produced by a factory `make_remember_tool(memory)` that closes over the store and returns a `@beta_async_tool` object — `build_orchestrator` calls the factory with the real `MemoryStore`.

**Files:**
- Create: `~/jarvis/jarvis/tools/builtin/local_tools.py`
- Test: `~/jarvis/tests/tools/test_local_tools.py`

Steps:

- [ ] **Step 1: Write the failing test (full code).** Create `~/jarvis/tests/tools/test_local_tools.py`:
```python
import asyncio

from jarvis.tools.builtin.local_tools import calc, make_remember_tool


def test_calc_adds_integers():
    assert asyncio.run(calc.call({"expression": "3 + 5"})) == "3 + 5 = 8"


def test_calc_handles_parens_and_precedence():
    assert asyncio.run(calc.call({"expression": "12 * (4 - 1)"})) == "12 * (4 - 1) = 36"


def test_calc_rejects_non_arithmetic_safely():
    out = asyncio.run(calc.call({"expression": "__import__('os').system('ls')"}))
    assert "계산할 수 없" in out  # no eval, no exception leaking — clean Korean error


def test_remember_tool_stores_via_memory_and_confirms():
    class FakeMemory:
        def __init__(self):
            self.notes = []

        def remember(self, note):
            self.notes.append(note)

    mem = FakeMemory()
    tool = make_remember_tool(mem)
    assert tool.name == "remember"
    out = asyncio.run(tool.call({"note": "내일 3시 회의"}))
    assert mem.notes == ["내일 3시 회의"]
    assert "내일 3시 회의" in out
```

- [ ] **Step 2: Run & show expected FAIL (genuine red — module absent).**
```bash
~/jarvis/.venv/bin/python -m pytest tests/tools/test_local_tools.py -q
```
Expected: `ModuleNotFoundError: No module named 'jarvis.tools.builtin.local_tools'`.

- [ ] **Step 3: Minimal implementation (full code).** Create `~/jarvis/jarvis/tools/builtin/local_tools.py`:
```python
from __future__ import annotations

import ast
import operator
from typing import Any

from anthropic import beta_async_tool

# SAFE arithmetic: an explicit AST whitelist — NO eval, NO names/calls/attrs.
_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _safe_eval(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError("지원하지 않는 식")


@beta_async_tool
async def calc(expression: str) -> str:
    """사칙연산 수식을 계산합니다.

    Args:
        expression: 계산할 산술식 (예: "3 + 5", "12 * (4 - 1)").
    """
    try:
        value: Any = _safe_eval(ast.parse(expression, mode="eval").body)
    except (ValueError, SyntaxError, ZeroDivisionError, TypeError, OverflowError) as exc:
        return f"계산할 수 없는 식입니다: {expression} ({exc})"
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return f"{expression} = {value}"


def make_remember_tool(memory: Any) -> Any:
    """Build a `remember` @beta_async_tool bound to a live MemoryStore.

    The closure captures ``memory`` so the decorated tool can persist notes via
    ``MemoryStore.remember`` while still exposing the .name/.to_dict()/.call()
    contract ToolRegistry expects.
    """

    @beta_async_tool
    async def remember(note: str) -> str:
        """사용자가 알려준 정보를 장기 기억에 저장합니다.

        Args:
            note: 기억할 내용 (예: "내일 3시 회의").
        """
        memory.remember(note)
        return f"기억했습니다: {note}"

    return remember
```

- [ ] **Step 4: Run & show expected PASS.**
```bash
~/jarvis/.venv/bin/python -m pytest tests/tools/test_local_tools.py -q
```
Expected: `4 passed`.

- [ ] **Step 5: Commit.**
```bash
git -C ~/jarvis add jarvis/tools/builtin/local_tools.py tests/tools/test_local_tools.py
git -C ~/jarvis commit -m "M3 Task3: local builtins calc (safe AST) + remember (MemoryStore.remember)"
```

---

### Task 4: Server-side web_search builtin (dict, non-local)

**Files:**
- Create: `~/jarvis/jarvis/tools/builtin/web_search.py`
- Test: `~/jarvis/tests/tools/test_web_search.py`

Steps:

- [ ] **Step 1: Write the failing test (full code).** Create `~/jarvis/tests/tools/test_web_search.py`:
```python
import asyncio

import pytest

from jarvis.tools.builtin.web_search import IS_LOCAL, WEB_SEARCH_TOOL
from jarvis.tools.registry import ToolRegistry


def test_web_search_tool_is_correct_server_dict():
    assert WEB_SEARCH_TOOL == {"type": "web_search_20260209", "name": "web_search"}
    assert IS_LOCAL is False


def test_web_search_registers_as_non_local():
    reg = ToolRegistry()
    reg.register(WEB_SEARCH_TOOL)
    assert WEB_SEARCH_TOOL in reg.tools()
    assert reg.is_gated("web_search") is False
    with pytest.raises(KeyError):
        asyncio.run(reg.dispatch("web_search", {}))
```

- [ ] **Step 2: Run & show expected FAIL (genuine red — module absent).**
```bash
~/jarvis/.venv/bin/python -m pytest tests/tools/test_web_search.py -q
```
Expected: `ModuleNotFoundError: No module named 'jarvis.tools.builtin.web_search'`.

- [ ] **Step 3: Minimal implementation (full code).** Create `~/jarvis/jarvis/tools/builtin/web_search.py`:
```python
from __future__ import annotations

# Server-side tool: Anthropic executes the search; the client never dispatches
# it. Latest version (web_search_20260209) supports dynamic filtering on
# claude-opus-4-8. Register the dict via ToolRegistry.register(WEB_SEARCH_TOOL).
WEB_SEARCH_TOOL: dict[str, str] = {
    "type": "web_search_20260209",
    "name": "web_search",
}

# Flag: this tool runs on Anthropic's servers, not locally.
IS_LOCAL: bool = False
```

- [ ] **Step 4: Run & show expected PASS.**
```bash
~/jarvis/.venv/bin/python -m pytest tests/tools/test_web_search.py -q
```
Expected: `2 passed`.

- [ ] **Step 5: Commit.**
```bash
git -C ~/jarvis add jarvis/tools/builtin/web_search.py tests/tools/test_web_search.py
git -C ~/jarvis commit -m "M3 Task4: server-side web_search_20260209 builtin (non-local)"
```

---

### Task 5: MCP client slot (AsyncExitStack + import-check + hand-rolled fallback + defer/tool-search)

**Files:**
- Create: `~/jarvis/jarvis/tools/mcp_client.py`
- Test: `~/jarvis/tests/tools/test_mcp_client.py`

Steps:

- [ ] **Step 1: Write the failing test (full code).** Create `~/jarvis/tests/tools/test_mcp_client.py`:
```python
import asyncio
import contextlib

import jarvis.tools.mcp_client as mc


class FakeContent:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class FakeResult:
    def __init__(self, content, isError=False):
        self.content = content
        self.isError = isError


class FakeSession:
    def __init__(self, result):
        self._result = result
        self.calls = []

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return self._result


class FakeMCPTool:
    def __init__(self, name, description, inputSchema):
        self.name = name
        self.description = description
        self.inputSchema = inputSchema


def test_handrolled_to_dict_and_call_maps_text_content():
    tool = FakeMCPTool("do_thing", "설명", {"type": "object", "properties": {}})
    sess = FakeSession(FakeResult([FakeContent("결과A"), FakeContent("결과B")]))
    w = mc.HandRolledMCPTool(tool, sess)
    d = w.to_dict()
    assert d["name"] == "do_thing"
    assert d["description"] == "설명"
    assert d["input_schema"] == {"type": "object", "properties": {}}
    assert "defer_loading" not in d
    assert asyncio.run(w.call({"a": 1})) == "결과A\n결과B"
    assert sess.calls == [("do_thing", {"a": 1})]


def test_handrolled_error_result_is_flagged():
    tool = FakeMCPTool("t", "d", {"type": "object"})
    sess = FakeSession(FakeResult([FakeContent("boom")], isError=True))
    w = mc.HandRolledMCPTool(tool, sess)
    assert asyncio.run(w.call({})).startswith("[MCP 오류]")


def test_handrolled_defer_loading_flag():
    tool = FakeMCPTool("t", "d", {"type": "object"})
    w = mc.HandRolledMCPTool(tool, FakeSession(FakeResult([])), defer_loading=True)
    assert w.to_dict()["defer_loading"] is True


def test_wrap_uses_handrolled_when_helper_absent(monkeypatch):
    monkeypatch.setattr(mc, "_HAS_MCP_HELPER", False)
    tool = FakeMCPTool("t", "d", {"type": "object"})
    w = mc.wrap_mcp_tool(tool, FakeSession(FakeResult([])))
    assert isinstance(w, mc.HandRolledMCPTool)


def test_premiere_stub_disabled_and_search_tool_constant():
    by_name = {s.name: s for s in mc.DEFAULT_MCP_SERVERS}
    assert "premiere-pro" in by_name
    assert by_name["premiere-pro"].enabled is False
    assert by_name["premiere-pro"].defer is True
    assert mc.TOOL_SEARCH_BM25 == {
        "type": "tool_search_tool_bm25_20251119",
        "name": "tool_search_tool_bm25",
    }


def test_load_mcp_tools_skips_disabled_servers():
    async def run():
        async with contextlib.AsyncExitStack() as stack:
            return await mc.load_mcp_tools(mc.DEFAULT_MCP_SERVERS, stack)

    tools, search = asyncio.run(run())
    assert tools == []
    assert search is None
```

- [ ] **Step 2: Run & show expected FAIL (genuine red — module absent).**
```bash
~/jarvis/.venv/bin/python -m pytest tests/tools/test_mcp_client.py -q
```
Expected: `ModuleNotFoundError: No module named 'jarvis.tools.mcp_client'`.

- [ ] **Step 3: Minimal implementation (full code).** Create `~/jarvis/jarvis/tools/mcp_client.py`:
```python
from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from typing import Any

# Startup import-check for the SDK MCP helper. async_mcp_tool signature
# (anthropic==0.107.1): async_mcp_tool(tool, session, *, cache_control=None,
# defer_loading=None, allowed_callers=None, eager_input_streaming=None,
# input_examples=None, strict=None) -> BetaAsyncFunctionTool. If the import
# fails (anthropic[mcp] absent), fall back to a hand-rolled wrapper.
try:  # pragma: no cover - exercised via monkeypatch in tests
    from anthropic.lib.tools.mcp import async_mcp_tool as _async_mcp_tool

    _HAS_MCP_HELPER = True
except Exception:  # noqa: BLE001
    _async_mcp_tool = None
    _HAS_MCP_HELPER = False

# BM25 tool-search tool (a TOOL TYPE, not a beta header). Used together with
# defer_loading=True for many-tool MCP servers.
TOOL_SEARCH_BM25: dict[str, str] = {
    "type": "tool_search_tool_bm25_20251119",
    "name": "tool_search_tool_bm25",
}


@dataclass
class MCPServerConfig:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    defer: bool = False  # many-tool server -> defer_loading + tool search


# Phase-2 stub: premiere-pro MCP server, left DISABLED until Phase 2.
DEFAULT_MCP_SERVERS: list[MCPServerConfig] = [
    MCPServerConfig(
        name="premiere-pro",
        command="node",
        args=["/opt/premiere-mcp/server.js"],
        env={},
        enabled=False,
        defer=True,
    ),
]


class HandRolledMCPTool:
    """Fallback wrapper used when async_mcp_tool is unavailable.

    Exposes the ToolRegistry contract: .name / .to_dict() / async .call().
    """

    def __init__(self, tool: Any, session: Any, *, defer_loading: bool = False) -> None:
        self._tool = tool
        self._session = session
        self._defer = defer_loading
        self.name: str = tool.name

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self._tool.name,
            "description": getattr(self._tool, "description", "") or "",
            "input_schema": getattr(self._tool, "inputSchema", {"type": "object"}),
        }
        if self._defer:
            d["defer_loading"] = True
        return d

    async def call(self, input: Any) -> str:
        result = await self._session.call_tool(self._tool.name, dict(input) if input else {})
        parts: list[str] = []
        for content in getattr(result, "content", None) or []:
            text = getattr(content, "text", None)
            parts.append(text if text is not None else str(content))
        out = "\n".join(parts)
        if getattr(result, "isError", False):
            return f"[MCP 오류] {out}"
        return out


def wrap_mcp_tool(tool: Any, session: Any, *, defer_loading: bool = False) -> Any:
    """Wrap a single MCP tool: SDK helper if present, else hand-rolled."""
    if _HAS_MCP_HELPER:
        return _async_mcp_tool(tool, session, defer_loading=defer_loading or None)
    return HandRolledMCPTool(tool, session, defer_loading=defer_loading)


async def load_mcp_tools(
    servers: list[MCPServerConfig],
    exit_stack: contextlib.AsyncExitStack,
) -> tuple[list[Any], dict[str, str] | None]:
    """Open enabled MCP servers via the exit stack and return wrapped tools.

    Returns (tools, search_tool); search_tool is TOOL_SEARCH_BM25 if any
    enabled server uses defer-loading, else None. mcp is imported lazily so the
    all-disabled path needs no mcp install. The exit_stack is owned by the
    caller and held open for the process lifetime.
    """
    tools: list[Any] = []
    need_search = False
    for cfg in servers:
        if not cfg.enabled:
            continue
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        params = StdioServerParameters(
            command=cfg.command,
            args=list(cfg.args),
            env=dict(cfg.env) or None,
        )
        read, write = await exit_stack.enter_async_context(stdio_client(params))
        session = await exit_stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        listed = await session.list_tools()
        for tool in listed.tools:
            tools.append(wrap_mcp_tool(tool, session, defer_loading=cfg.defer))
        if cfg.defer:
            need_search = True
    return tools, (TOOL_SEARCH_BM25 if need_search else None)
```

- [ ] **Step 4: Run & show expected PASS.**
```bash
~/jarvis/.venv/bin/python -m pytest tests/tools/test_mcp_client.py -q
```
Expected: `6 passed`.

- [ ] **Step 5: Manual verification — confirm the SDK MCP helper import-check resolves on this machine.** Run:
```bash
~/jarvis/.venv/bin/python -c "import jarvis.tools.mcp_client as m; print('helper_available=', m._HAS_MCP_HELPER)"
```
Expected observable: prints `helper_available= True` on a working `anthropic[mcp]==0.107.1` install (the hand-rolled fallback path is still covered by `test_wrap_uses_handrolled_when_helper_absent`). If it prints `False`, the hand-rolled wrapper is used automatically — no code change needed.

- [ ] **Step 6: Commit.**
```bash
git -C ~/jarvis add jarvis/tools/mcp_client.py tests/tools/test_mcp_client.py
git -C ~/jarvis commit -m "M3 Task5: MCP client slot (AsyncExitStack, import-check, defer/bm25, premiere stub)"
```

---

### Task 6: Real voice-confirm — `VoiceConfirm` (TTS → PTT → STT → Korean yes/no parser)

Gated tools must be confirmed by a REAL voice prompt, not an auto-yes. `VoiceConfirm.confirm(prompt)` speaks the prompt through the live TTS→VC→playback path, records a short reply window from the mic, runs STT, and parses the Korean answer into a `bool`. The pure parser `parse_korean_confirmation` is unit-tested; the live capture path is manual-verified. `confirm` is injected as `Brain.confirm`.

**Files:**
- Create: `~/jarvis/jarvis/tools/confirm.py`
- Test: `~/jarvis/tests/tools/test_confirm.py`

Steps:

- [ ] **Step 1: Write the failing test (full code).** Create `~/jarvis/tests/tools/test_confirm.py`:
```python
from jarvis.tools.confirm import VoiceConfirm, parse_korean_confirmation


def test_parse_yes_variants():
    for s in ["네", "예", "응", "네 진행해주세요", "응 그래 좋아"]:
        assert parse_korean_confirmation(s) is True


def test_parse_no_variants():
    for s in ["아니", "아니오", "아니요", "취소해줘", "그만"]:
        assert parse_korean_confirmation(s) is False


def test_parse_unclear_returns_none():
    assert parse_korean_confirmation("") is None
    assert parse_korean_confirmation("   ") is None
    assert parse_korean_confirmation("음 글쎄요") is None


def test_negative_takes_priority_for_safety():
    # Ambiguous "아니 네" must NOT confirm an irreversible action.
    assert parse_korean_confirmation("아니 네") is False


def test_voiceconfirm_exposes_async_confirm():
    import inspect

    vc = VoiceConfirm(
        tts=None, vc=None, playback=None, capture=None, stt=None, settings=None
    )
    assert inspect.iscoroutinefunction(vc.confirm)
```

- [ ] **Step 2: Run & show expected FAIL (genuine red — module absent).**
```bash
~/jarvis/.venv/bin/python -m pytest tests/tools/test_confirm.py -q
```
Expected: `ModuleNotFoundError: No module named 'jarvis.tools.confirm'`.

- [ ] **Step 3: Minimal implementation (full code).** Create `~/jarvis/jarvis/tools/confirm.py`:
```python
from __future__ import annotations

import asyncio
from typing import Any

_YES: tuple[str, ...] = ("네", "예", "응", "그래", "좋아", "진행", "확인", "맞아", "yes", "ok", "오케이")
_NO: tuple[str, ...] = ("아니", "아니오", "아니요", "취소", "안돼", "안 돼", "그만", "하지마", "싫", "no")


def parse_korean_confirmation(text: str) -> bool | None:
    """Parse a short Korean utterance into yes(True)/no(False)/unclear(None).

    Negatives are checked FIRST: for an irreversible action, anything that
    sounds like refusal must block, so an ambiguous reply never confirms.
    """
    t = text.strip().lower()
    if not t:
        return None
    if any(k in t for k in _NO):
        return False
    if any(k in t for k in _YES):
        return True
    return None


class VoiceConfirm:
    """Real voice confirmation for gated tools.

    Speaks the prompt through the live TTS->VC->playback path, records a short
    reply window from the mic, transcribes it, and parses a Korean yes/no.
    Injected as ``Brain.confirm``. The parser is unit-tested; the live capture
    path is manual-verified.
    """

    def __init__(
        self,
        *,
        tts: Any,
        vc: Any,
        playback: Any,
        capture: Any,
        stt: Any,
        settings: Any,
        window_s: float = 4.0,
    ) -> None:
        self._tts = tts
        self._vc = vc
        self._playback = playback
        self._capture = capture
        self._stt = stt
        self._settings = settings
        self._window_s = window_s

    async def confirm(self, prompt: str) -> bool:
        await self._speak(
            f"{prompt} 진행하려면 '네', 취소하려면 '아니오'라고 말씀해 주세요."
        )
        self._capture.start()
        await asyncio.sleep(self._window_s)
        pcm = self._capture.stop()
        text = await asyncio.to_thread(
            self._stt.transcribe, pcm, 16000, self._settings.language
        )
        return parse_korean_confirmation(text) is True

    async def _speak(self, text: str) -> None:
        # Lazy import keeps module import light (parser tests need no soxr).
        from jarvis.audio.util import resample

        audio = await self._tts.synth(text)
        converted = await asyncio.to_thread(self._vc.convert, audio, self._tts.sample_rate)
        out = resample(converted, self._vc.sample_rate, self._settings.playback_rate)
        self._playback.feed(out)
        # Let the prompt finish before opening the reply window.
        await asyncio.sleep(len(out) / self._settings.playback_rate)
```

- [ ] **Step 4: Run & show expected PASS.**
```bash
~/jarvis/.venv/bin/python -m pytest tests/tools/test_confirm.py -q
```
Expected: `5 passed`.

- [ ] **Step 5: Manual verification (live — non-testable: real mic + audio).** With models warmed, exercise one round trip:
```bash
~/jarvis/.venv/bin/python -c "
import asyncio
from jarvis.core.config import Settings
from jarvis.audio.capture import MicCapture
from jarvis.audio.playback import Playback
from jarvis.stt.mlx_whisper import MLXWhisperSTT
from jarvis.tts.factory import make_tts
from jarvis.vc.factory import make_vc
from jarvis.tools.confirm import VoiceConfirm
s = Settings()
tts = make_tts(s); vc = make_vc(s); pb = Playback(sample_rate=s.playback_rate)
cap = MicCapture(sample_rate=16000); stt = MLXWhisperSTT(s.stt_repo, language=s.language)
tts.warm(); vc.warm(); stt.warm(); pb.start()
conf = VoiceConfirm(tts=tts, vc=vc, playback=pb, capture=cap, stt=stt, settings=s, window_s=4.0)
print('RESULT:', asyncio.run(conf.confirm('파일을 삭제할까요?')))
"
```
Expected observable: JARVIS speaks the Korean confirmation prompt; you say `네` (prints `RESULT: True`) or `아니오` (prints `RESULT: False`).

- [ ] **Step 6: Commit.**
```bash
git -C ~/jarvis add jarvis/tools/confirm.py tests/tools/test_confirm.py
git -C ~/jarvis commit -m "M3 Task6: real VoiceConfirm (TTS->PTT->STT) + korean yes/no parser"
```

---

### Task 7: Brain upgrade — ADD keyword router + voice filler + manual gated streaming tool loop (extend M1, migrate test_brain.py)

This EXTENDS the M1 Brain additively per the AMENDED CONTRACT: the canonical signature is `__init__(self, settings, memory, persona_text, client=None, *, registry=None, confirm=None)` — the M1 positional members are unchanged; M3 only ADDS keyword-only `registry`/`confirm`. `async warm()`, `last_usage`, the two-block cached system prompt (persona cached + memory/guidance uncached), and `_GUIDANCE` are RETAINED on BOTH the conversational (Haiku) and task (Opus) paths. The M1 `tests/test_brain.py` is re-run in this same task and stays green (the change is purely additive).

**Files:**
- Modify (additive replace): `~/jarvis/jarvis/brain/claude.py`
- Test: `~/jarvis/tests/brain/test_brain_tools.py`
- Verify (migrate, no edit expected): `~/jarvis/tests/test_brain.py`

Steps:

- [ ] **Step 1: Write the failing test (full code).** Create `~/jarvis/tests/brain/test_brain_tools.py`:
```python
import asyncio
from dataclasses import dataclass
from typing import Any

from anthropic import beta_async_tool

from jarvis.brain.claude import Brain, TASK_FILLER, route
from jarvis.tools.builtin.time_weather import get_time
from jarvis.tools.registry import ToolRegistry

_PERSONA = "가" * 5000  # stand-in for the real >=4096-token cached persona prefix


@dataclass
class TextBlock:
    text: str
    type: str = "text"


@dataclass
class ToolUseBlock:
    id: str
    name: str
    input: dict
    type: str = "tool_use"


@dataclass
class FakeMessage:
    content: list
    stop_reason: str
    usage: Any = None


class _FakeStream:
    def __init__(self, deltas, final):
        self._deltas = deltas
        self._final = final

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    @property
    def text_stream(self):
        async def gen():
            for d in self._deltas:
                yield d

        return gen()

    async def get_final_message(self):
        return self._final


class FakeMessages:
    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.calls = []

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        deltas, final = self._scripted.pop(0)
        return _FakeStream(deltas, final)


class FakeAnthropic:
    def __init__(self, scripted):
        self.messages = FakeMessages(scripted)


class FakeMemory:
    def text(self):
        return "사용자 이름은 이성재."


@dataclass
class FakeSettings:
    model_task: str = "claude-opus-4-8"
    model_conversational: str = "claude-haiku-4-5"


def _collect(brain, text):
    async def run():
        return [d async for d in brain.respond(text)]

    return asyncio.run(run())


def test_route_keyword_heuristic():
    assert route("지금 몇 시야?") == "task"
    assert route("날씨 알려줘") == "task"
    assert route("뉴스 검색해줘") == "task"
    assert route("3 더하기 5 알려주고 메모해줘") == "task"
    assert route("안녕 오늘 기분 어때?") == "conversational"
    assert route("고마워") == "conversational"


def test_conversational_path_uses_haiku_two_block_cache_no_tools():
    scripted = [(["안녕하세요!"], FakeMessage([TextBlock("안녕하세요!")], "end_turn"))]
    client = FakeAnthropic(scripted)

    async def confirm(prompt):
        return True

    brain = Brain(FakeSettings(), FakeMemory(), _PERSONA, client=client, confirm=confirm)
    out = _collect(brain, "안녕")
    assert "".join(out) == "안녕하세요!"
    kw = client.messages.calls[0]
    assert kw["model"] == "claude-haiku-4-5"
    assert "tools" not in kw
    assert "thinking" not in kw
    assert "output_config" not in kw
    # Two-block system: cached persona prefix, then uncached memory+guidance.
    assert kw["system"][0]["text"] == _PERSONA
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in kw["system"][1]
    assert "이성재" in kw["system"][1]["text"]   # memory present
    assert "최종" in kw["system"][1]["text"]      # final-answer-only guidance present


def test_task_path_emits_voice_filler_before_opus_turn():
    scripted = [
        (["답입니다."], FakeMessage([TextBlock("답입니다.")], "end_turn")),
    ]
    client = FakeAnthropic(scripted)

    async def confirm(prompt):
        return True

    brain = Brain(FakeSettings(), FakeMemory(), _PERSONA, client=client,
                  registry=ToolRegistry(), confirm=confirm)
    out = _collect(brain, "지금 몇 시야?")
    assert out[0] == TASK_FILLER          # filler spoken FIRST, before the slow turn
    assert "".join(out[1:]) == "답입니다."


def test_task_path_dispatches_ungated_tool():
    scripted = [
        (
            ["시간을 확인할게요. "],
            FakeMessage(
                [TextBlock("시간을 확인할게요. "), ToolUseBlock("t1", "get_time", {})],
                "tool_use",
            ),
        ),
        (["지금은 오후 3시입니다."], FakeMessage([TextBlock("지금은 오후 3시입니다.")], "end_turn")),
    ]
    client = FakeAnthropic(scripted)
    reg = ToolRegistry()
    reg.register(get_time)
    confirm_calls = []

    async def confirm(prompt):
        confirm_calls.append(prompt)
        return True

    brain = Brain(FakeSettings(), FakeMemory(), _PERSONA, client=client, registry=reg, confirm=confirm)
    out = _collect(brain, "지금 몇 시야?")
    assert out[0] == TASK_FILLER
    assert "오후 3시" in "".join(out)
    assert confirm_calls == []  # get_time is not gated
    first = client.messages.calls[0]
    assert first["model"] == "claude-opus-4-8"
    assert first["thinking"] == {"type": "adaptive"}
    assert first["output_config"] == {"effort": "high"}
    assert first["tools"] == reg.tools()
    tool_result = client.messages.calls[1]["messages"][-1]["content"][0]
    assert tool_result["type"] == "tool_result"
    assert tool_result["tool_use_id"] == "t1"
    assert "시" in tool_result["content"]


def test_gated_tool_declined_blocks_execution():
    executed = {"v": False}

    @beta_async_tool
    async def delete_file(path: str) -> str:
        """파일을 영구 삭제합니다.

        Args:
            path: 삭제할 파일 경로.
        """
        executed["v"] = True
        return "삭제됨"

    scripted = [
        ([], FakeMessage([ToolUseBlock("d1", "delete_file", {"path": "/tmp/x"})], "tool_use")),
        (["요청을 취소했습니다."], FakeMessage([TextBlock("요청을 취소했습니다.")], "end_turn")),
    ]
    client = FakeAnthropic(scripted)
    reg = ToolRegistry()
    reg.register(delete_file, gated=True)
    prompts = []

    async def confirm(prompt):
        prompts.append(prompt)
        return False

    brain = Brain(FakeSettings(), FakeMemory(), _PERSONA, client=client, registry=reg, confirm=confirm)
    out = _collect(brain, "파일 삭제 실행해줘")
    assert executed["v"] is False
    assert len(prompts) == 1 and "delete_file" in prompts[0]
    tool_result = client.messages.calls[1]["messages"][-1]["content"][0]
    assert tool_result["type"] == "tool_result" and "취소" in tool_result["content"]
    assert out[0] == TASK_FILLER
    assert "".join(out[1:]).endswith("취소했습니다.")


def test_gated_tool_approved_runs():
    executed = {"v": False}

    @beta_async_tool
    async def delete_file(path: str) -> str:
        """파일을 영구 삭제합니다.

        Args:
            path: 삭제할 파일 경로.
        """
        executed["v"] = True
        return "삭제 완료"

    scripted = [
        ([], FakeMessage([ToolUseBlock("d1", "delete_file", {"path": "/tmp/x"})], "tool_use")),
        (["삭제했습니다."], FakeMessage([TextBlock("삭제했습니다.")], "end_turn")),
    ]
    client = FakeAnthropic(scripted)
    reg = ToolRegistry()
    reg.register(delete_file, gated=True)

    async def confirm(prompt):
        return True

    brain = Brain(FakeSettings(), FakeMemory(), _PERSONA, client=client, registry=reg, confirm=confirm)
    out = _collect(brain, "파일 삭제 실행해줘")
    assert executed["v"] is True
    tool_result = client.messages.calls[1]["messages"][-1]["content"][0]
    assert "삭제 완료" in tool_result["content"]
    assert out[0] == TASK_FILLER
    assert "".join(out[1:]) == "삭제했습니다."


def test_pause_turn_resends_without_tool_result():
    scripted = [
        (["검색 중..."], FakeMessage([TextBlock("검색 중...")], "pause_turn")),
        (["결과입니다."], FakeMessage([TextBlock("결과입니다.")], "end_turn")),
    ]
    client = FakeAnthropic(scripted)
    reg = ToolRegistry()
    reg.register({"type": "web_search_20260209", "name": "web_search"})

    async def confirm(prompt):
        return True

    brain = Brain(FakeSettings(), FakeMemory(), _PERSONA, client=client, registry=reg, confirm=confirm)
    out = _collect(brain, "최신 뉴스 검색해줘")
    assert out[0] == TASK_FILLER
    assert "".join(out[1:]) == "검색 중...결과입니다."
    # Second call carries the assistant turn but NO tool_result user message.
    second = client.messages.calls[1]["messages"]
    assert second[-1]["role"] == "assistant"
```

- [ ] **Step 2: Run & show expected FAIL (genuine red — `route`/`TASK_FILLER`/tool loop truly absent from the M1 Brain).**
```bash
~/jarvis/.venv/bin/python -m pytest tests/brain/test_brain_tools.py -q
```
Expected: `ImportError: cannot import name 'route' from 'jarvis.brain.claude'` (the M1 file has a conversational-only `Brain` with no `route`, no `TASK_FILLER`, and no tool loop — the symbols genuinely do not exist yet).

- [ ] **Step 3: Implement by additively replacing the file (full code).** Replace the entire contents of `~/jarvis/jarvis/brain/claude.py`. This SUPERSEDES the M1 conversational-only file while keeping the M1 positional signature `(settings, memory, persona_text, client=None)`, `warm()`, `last_usage`, the two-block cached system prompt, and `_GUIDANCE` — and ADDS keyword-only `registry`/`confirm`, the keyword `route`, the `잠시만요` filler, and the manual gated streaming tool loop:
```python
from __future__ import annotations

from typing import Any, AsyncIterator, Awaitable, Callable, Optional

from anthropic import AsyncAnthropic

# Final-answer-only guidance — MUST be present on BOTH the conversational
# (Haiku) and task (Opus) paths. Korean: speak only the final answer, no
# preamble/reasoning/meta. (Identical to M1 so tests/test_brain.py stays green.)
_GUIDANCE = (
    "너는 자비스, 음성으로 답하는 한국어 집사다. 최종적으로 말할 한국어 답변만 출력하라. "
    "사고 과정, 머리말, 맺음말, '음' 같은 군더더기 없이 핵심부터 간결하게 답하라."
)

# Spoken filler emitted before the multi-second Opus turn (spec 6.4 / 9.4).
TASK_FILLER = "잠시만요."

# Keyword heuristic router: a real-world action or a fact that needs a tool
# takes the TASK path (opus + tools); everything else converses on Haiku.
_TASK_KEYWORDS: tuple[str, ...] = (
    "시간", "몇 시", "지금 몇", "날씨", "기온", "온도",
    "검색", "찾아", "뉴스", "주가", "환율", "일정", "예약",
    "실행", "열어", "켜", "꺼", "삭제", "보내", "추가", "편집",
    "계산", "더하기", "빼기", "곱하기", "나누기", "메모", "기억해", "저장",
    "time", "weather", "search", "news",
)

_MAX_TOOL_ITERATIONS = 8


def route(user_text: str) -> str:
    """Return 'task' or 'conversational' from a keyword heuristic."""
    text = user_text.strip()
    return "task" if any(k in text for k in _TASK_KEYWORDS) else "conversational"


class Brain:
    """Streams Claude responses: conversational path (M1) + manual gated tool loop (M3).

    Conversational (Haiku) and TASK (Opus) paths both use a two-block system
    prompt — [persona, cache_control ephemeral] then [memory + final-answer-only
    guidance, NO cache_control] — so memory/guidance changes never bust the
    cached persona prefix. The TASK path emits a short ``잠시만요`` filler, then
    drives claude-opus-4-8 with adaptive thinking + high effort through a manual
    streaming tool loop: it detects tool_use blocks, voice-confirms gated
    (irreversible) tools via the injected ``confirm`` callback before dispatch,
    feeds tool_result blocks back, and re-streams until the model stops.
    """

    def __init__(
        self,
        settings: Any,
        memory: Any,
        persona_text: str,
        client: Optional[AsyncAnthropic] = None,
        *,
        registry: Any = None,
        confirm: Optional[Callable[[str], Awaitable[bool]]] = None,
    ) -> None:
        self._settings = settings
        self._memory = memory
        self._persona = persona_text  # real >=4096-token persona; NO empty fallback
        self._client = client or AsyncAnthropic(api_key=settings.api_key)
        self._registry = registry
        self._confirm = confirm
        self.last_usage = None

    # ----- system prompt (two blocks: cached persona, then uncached memory+guidance) -----
    def _persona_block(self) -> dict[str, Any]:
        # Stable cached prefix (>=4096 tokens). Byte-identical in warm() and respond().
        return {"type": "text", "text": self._persona, "cache_control": {"type": "ephemeral"}}

    def _system(self) -> list[dict[str, Any]]:
        memory_text = self._memory.text().strip() if self._memory is not None else ""
        tail = (f"# 기억\n{memory_text}\n\n" if memory_text else "") + _GUIDANCE
        # Memory/guidance go AFTER the cache breakpoint so the persona stays cached.
        return [self._persona_block(), {"type": "text", "text": tail}]

    async def warm(self) -> None:
        # Pre-warm: non-streaming max_tokens=0 over the same cached persona prefix.
        await self._client.messages.create(
            model=self._settings.model_conversational,
            max_tokens=0,
            system=[self._persona_block()],
            messages=[{"role": "user", "content": "warmup"}],
        )

    async def respond(self, user_text: str) -> AsyncIterator[str]:
        if route(user_text) == "conversational":
            async for delta in self._conversational(user_text):
                yield delta
        else:
            async for delta in self._task(user_text):
                yield delta

    async def _conversational(self, user_text: str) -> AsyncIterator[str]:
        # Haiku: no thinking, no effort, no tools. Final spoken answer only.
        async with self._client.messages.stream(
            model=self._settings.model_conversational,
            max_tokens=1024,
            system=self._system(),
            messages=[{"role": "user", "content": user_text}],
        ) as stream:
            async for text in stream.text_stream:
                yield text
            final = await stream.get_final_message()
            self.last_usage = getattr(final, "usage", None)

    async def _task(self, user_text: str) -> AsyncIterator[str]:
        # Spoken filler BEFORE the slow Opus turn (spec 6.4 / 9.4).
        yield TASK_FILLER
        tools = self._registry.tools() if self._registry is not None else []
        messages: list[dict[str, Any]] = [{"role": "user", "content": user_text}]
        for _ in range(_MAX_TOOL_ITERATIONS):
            async with self._client.messages.stream(
                model=self._settings.model_task,
                max_tokens=2048,
                system=self._system(),
                tools=tools,
                thinking={"type": "adaptive"},
                output_config={"effort": "high"},
                messages=messages,
            ) as stream:
                async for text in stream.text_stream:
                    yield text
                final = await stream.get_final_message()
            self.last_usage = getattr(final, "usage", None)

            # Preserve the full assistant turn (incl. thinking blocks).
            messages.append({"role": "assistant", "content": final.content})

            if final.stop_reason == "pause_turn":
                # Server tool still running; resend without a tool_result.
                continue

            tool_uses = [b for b in final.content if getattr(b, "type", None) == "tool_use"]
            if not tool_uses:
                return

            results: list[dict[str, Any]] = []
            for block in tool_uses:
                results.append(await self._run_tool(block))
            messages.append({"role": "user", "content": results})

    async def _run_tool(self, block: Any) -> dict[str, Any]:
        name = block.name
        tool_use_id = block.id
        args = block.input or {}
        if self._registry.is_gated(name):
            approved = False
            if self._confirm is not None:
                approved = await self._confirm(self._confirm_prompt(name, args))
            if not approved:
                return {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": "사용자가 이 작업의 실행을 취소했습니다.",
                }
        try:
            output = await self._registry.dispatch(name, args)
        except Exception as exc:  # noqa: BLE001
            return {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": f"도구 실행 오류: {exc}",
                "is_error": True,
            }
        return {"type": "tool_result", "tool_use_id": tool_use_id, "content": output}

    @staticmethod
    def _confirm_prompt(name: str, args: Any) -> str:
        return f"'{name}' 작업을 실행할까요? 입력값은 {args} 입니다."
```

- [ ] **Step 4: Run & show expected PASS.**
```bash
~/jarvis/.venv/bin/python -m pytest tests/brain/test_brain_tools.py -q
```
Expected: `7 passed`.

- [ ] **Step 5: Migrate M1 `tests/test_brain.py` — re-run and confirm it stays green.** The M3 signature only ADDS keyword-only `registry`/`confirm` and preserves the persona block, two-block system, `warm()`, and `last_usage`, so the M1 test (`Brain(Settings(), _Mem(), persona, client=fake)`) needs no edit. Run:
```bash
~/jarvis/.venv/bin/python -m pytest tests/test_brain.py -q
```
Expected: `2 passed`. (If it had regressed, the fix belongs in THIS task — but the additive change keeps it green.)

- [ ] **Step 6: Commit.**
```bash
git -C ~/jarvis add jarvis/brain/claude.py tests/brain/test_brain_tools.py
git -C ~/jarvis commit -m "M3 Task7: Brain additive upgrade (route + 잠시만요 filler + gated tool loop); M1 test_brain green"
```

---

### Task 8: Wiring — `build_orchestrator` builds ToolRegistry + VoiceConfirm + MCP exit-stack + extended Brain

Per the AMENDED CONTRACT, ALL backend/tool/Brain construction lives in `jarvis.__main__.build_orchestrator`, never in `Orchestrator.__init__` (which stays pure keyword-only DI). This task makes `build_orchestrator` async (it now awaits MCP loading), builds the shared backends + the `ToolRegistry` (get_time/get_weather/web_search/remember/calc), the real `VoiceConfirm`, loads MCP tools through a caller-owned `AsyncExitStack` held open for the process lifetime, builds `Brain(settings, memory, persona, client=client, registry=registry, confirm=confirmer.confirm)`, and injects everything into the canonical DI `Orchestrator`. The result reaches the live PTT→STT→Brain→TTS pipeline.

**Files:**
- Modify (full replace): `~/jarvis/jarvis/__main__.py`
- Test (migrate to async + assert wiring): `~/jarvis/tests/test_main_wiring.py`

Steps:

- [ ] **Step 1: Replace the wiring test with the async, registry-aware version (full code).** Overwrite `~/jarvis/tests/test_main_wiring.py`:
```python
import asyncio

from jarvis.__main__ import build_orchestrator
from jarvis.core.orchestrator import Orchestrator


class _FakeAnthropic:
    class _M:
        def stream(self, **k):  # pragma: no cover - not called in wiring test
            raise AssertionError

        async def create(self, **k):  # pragma: no cover
            raise AssertionError

    def __init__(self):
        self.messages = self._M()


def _build():
    return asyncio.run(build_orchestrator(client=_FakeAnthropic()))


def test_build_orchestrator_wires_all_components():
    orch = _build()
    assert isinstance(orch, Orchestrator)
    assert orch.stt is not None
    assert orch.brain is not None
    assert orch.tts.sample_rate > 0
    assert orch.vc is not None
    assert orch.playback.sample_rate == 48000
    assert orch.activator is not None
    assert orch.capture is not None


def test_build_orchestrator_registers_builtin_tools():
    orch = _build()
    names = {d.get("name") for d in orch.brain._registry.tools()}
    assert {"get_time", "get_weather", "web_search", "remember", "calc"} <= names


def test_build_orchestrator_injects_voice_confirm():
    orch = _build()
    assert callable(orch.brain._confirm)
```

- [ ] **Step 2: Run & show expected FAIL (genuine red — wiring behavior absent).**
```bash
~/jarvis/.venv/bin/python -m pytest tests/test_main_wiring.py -q
```
Expected: a genuine failure on missing behavior — against the M1 `build_orchestrator` (sync, no registry, no confirm), `asyncio.run(build_orchestrator(...))` raises `TypeError: An asyncio.Future, a coroutine or an awaitable is required` (M1's `build_orchestrator` returns an `Orchestrator`, not a coroutine), and the registry/confirm assertions have no wiring to satisfy.

- [ ] **Step 3: Implement — replace `~/jarvis/jarvis/__main__.py` (full code).**
```python
from __future__ import annotations

import asyncio
import contextlib
import os
from typing import Optional

from anthropic import AsyncAnthropic

from .activation.ptt import PushToTalk
from .audio.capture import MicCapture
from .audio.playback import Playback
from .brain.claude import Brain
from .brain.memory import MemoryStore
from .brain.persona import load_persona
from .brain.sentence import SentenceChunker
from .core.config import Settings
from .core.orchestrator import Orchestrator
from .stt.mlx_whisper import MLXWhisperSTT
from .tts.factory import make_tts
from .vc.factory import make_vc
from .tools.confirm import VoiceConfirm
from .tools.registry import ToolRegistry
from .tools.builtin.time_weather import get_time, get_weather
from .tools.builtin.web_search import WEB_SEARCH_TOOL
from .tools.builtin.local_tools import calc, make_remember_tool
from .tools.mcp_client import DEFAULT_MCP_SERVERS, load_mcp_tools


async def build_orchestrator(
    *,
    client: Optional[AsyncAnthropic] = None,
    exit_stack: Optional[contextlib.AsyncExitStack] = None,
) -> Orchestrator:
    """Construct the full assistant. ALL backend/tool/Brain construction lives
    HERE — never in Orchestrator.__init__. When ``exit_stack`` is supplied (by
    _amain, held open for the process lifetime) any enabled MCP servers are
    loaded into the registry through it.
    """
    settings = Settings()
    memory = MemoryStore(settings.memory_path)
    memory.load()
    persona = load_persona(settings.persona_path)  # real >=4096-token persona; no fallback

    # Shared backends (constructed here, then dependency-injected).
    activator = PushToTalk(settings.ptt_key)
    capture = MicCapture(sample_rate=16000)
    stt = MLXWhisperSTT(settings.stt_repo, language=settings.language)
    tts = make_tts(settings)
    vc = make_vc(settings)
    playback = Playback(sample_rate=settings.playback_rate)
    chunker = SentenceChunker()

    # Real voice confirmation for gated (irreversible) tools.
    confirmer = VoiceConfirm(
        tts=tts, vc=vc, playback=playback, capture=capture, stt=stt, settings=settings
    )

    # Tool catalog: local builtins + server web_search + remember + calc.
    registry = ToolRegistry()
    registry.register(get_time)
    registry.register(get_weather)
    registry.register(WEB_SEARCH_TOOL)
    registry.register(make_remember_tool(memory))
    registry.register(calc)

    # MCP tools via the caller-owned AsyncExitStack (held open for process life).
    if exit_stack is not None:
        mcp_tools, _search = await load_mcp_tools(DEFAULT_MCP_SERVERS, exit_stack)
        for tool in mcp_tools:
            registry.register(tool, gated=True)  # MCP actions are irreversible

    brain = Brain(
        settings,
        memory,
        persona,
        client=client,
        registry=registry,
        confirm=confirmer.confirm,
    )

    return Orchestrator(
        settings=settings,
        activator=activator,
        capture=capture,
        stt=stt,
        brain=brain,
        chunker=chunker,
        tts=tts,
        vc=vc,
        playback=playback,
    )


async def _amain() -> None:
    # AsyncExitStack stays open for the whole process lifetime (MCP sessions live).
    async with contextlib.AsyncExitStack() as stack:
        orch = await build_orchestrator(exit_stack=stack)
        # Warm models + persona cache before listening.
        orch.stt.warm()
        orch.tts.warm()
        orch.vc.warm()
        await orch.brain.warm()
        print("자비스 준비 완료. 오른쪽 옵션 키를 누른 채 말씀하세요. (Ctrl+C로 종료)")
        await orch.run()


def main() -> None:
    # After the first model download, run with HF_HUB_OFFLINE=1 for fully local STT.
    os.environ.setdefault("HF_HUB_OFFLINE", os.environ.get("HF_HUB_OFFLINE", "0"))
    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        print("\n종료합니다.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run & show expected PASS.**
```bash
~/jarvis/.venv/bin/python -m pytest tests/test_main_wiring.py -q
```
Expected: `3 passed`.

- [ ] **Step 5: Commit.**
```bash
git -C ~/jarvis add jarvis/__main__.py tests/test_main_wiring.py
git -C ~/jarvis commit -m "M3 Task8: build_orchestrator wires ToolRegistry + VoiceConfirm + MCP exit-stack + extended Brain"
```

---

### Task 9: Integration — heterogeneous tools, Korean tool request, voice-gated irreversible tool, calc+memo end-to-end (+ live-API manual check)

Tasks 1–8 supply every symbol this integration test exercises, so when first written and run it passes GREEN — this is the milestone composition/verification gate, NOT a unit red phase (the genuine red phases live in Tasks 1–8, where new modules/symbols were truly absent). It composes the real units (Brain tool loop, builtins, web_search, MCP wrapper) through a fake Anthropic client and covers the spec acceptance `"3 더하기 5 알려주고 메모해줘"` end-to-end.

**Files:**
- Create: `~/jarvis/tests/integration/test_tool_gating.py`
- Create: `~/jarvis/scripts/manual_tool_check.py`

Steps:

- [ ] **Step 1: Write the integration test (full code).** Create `~/jarvis/tests/integration/test_tool_gating.py`:
```python
import asyncio
from dataclasses import dataclass
from typing import Any

import jarvis.tools.mcp_client as mc
from jarvis.brain.claude import Brain, TASK_FILLER
from jarvis.tools.builtin.local_tools import calc, make_remember_tool
from jarvis.tools.builtin.time_weather import get_time, get_weather
from jarvis.tools.builtin.web_search import WEB_SEARCH_TOOL
from jarvis.tools.registry import ToolRegistry

_PERSONA = "가" * 5000


@dataclass
class TextBlock:
    text: str
    type: str = "text"


@dataclass
class ToolUseBlock:
    id: str
    name: str
    input: dict
    type: str = "tool_use"


@dataclass
class FakeMessage:
    content: list
    stop_reason: str
    usage: Any = None


class _FakeStream:
    def __init__(self, deltas, final):
        self._deltas = deltas
        self._final = final

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    @property
    def text_stream(self):
        async def gen():
            for d in self._deltas:
                yield d

        return gen()

    async def get_final_message(self):
        return self._final


class FakeMessages:
    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.calls = []

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        deltas, final = self._scripted.pop(0)
        return _FakeStream(deltas, final)


class FakeAnthropic:
    def __init__(self, scripted):
        self.messages = FakeMessages(scripted)


class FakeMemory:
    def __init__(self):
        self.notes = []

    def text(self):
        return "사용자 이름은 이성재."

    def remember(self, note):
        self.notes.append(note)


@dataclass
class FakeSettings:
    model_task: str = "claude-opus-4-8"
    model_conversational: str = "claude-haiku-4-5"


class FakeContent:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class FakeResult:
    def __init__(self, content, isError=False):
        self.content = content
        self.isError = isError


class FakeSession:
    def __init__(self, result):
        self._result = result

    async def call_tool(self, name, arguments):
        return self._result


class FakeMCPTool:
    def __init__(self, name, description, inputSchema):
        self.name = name
        self.description = description
        self.inputSchema = inputSchema


def _collect(brain, text):
    async def run():
        return [d async for d in brain.respond(text)]

    return asyncio.run(run())


def _registry_with_all_kinds(memory):
    reg = ToolRegistry()
    reg.register(get_time)                 # @beta_async_tool (local, ungated)
    reg.register(get_weather)              # @beta_async_tool (local, ungated)
    reg.register(calc)                     # @beta_async_tool (local, ungated)
    reg.register(make_remember_tool(memory))  # closure-bound local (ungated)
    reg.register(WEB_SEARCH_TOOL)          # server-side dict (non-local)
    mcp_tool = mc.HandRolledMCPTool(       # MCP-wrapped tool (local, gated)
        FakeMCPTool("premiere_add_clip", "타임라인에 클립 추가", {"type": "object"}),
        FakeSession(FakeResult([FakeContent("ok")])),
    )
    reg.register(mcp_tool, gated=True)
    return reg


def test_heterogeneous_tools_coexist():
    reg = _registry_with_all_kinds(FakeMemory())
    defs = reg.tools()
    names = {d.get("name") for d in defs}
    assert {"get_time", "get_weather", "calc", "remember", "web_search", "premiere_add_clip"} <= names
    assert {"type": "web_search_20260209", "name": "web_search"} in defs
    assert reg.is_gated("premiere_add_clip") is True
    assert reg.is_gated("get_time") is False
    assert reg.is_gated("web_search") is False


def test_korean_time_request_triggers_tool_and_spoken_answer():
    reg = _registry_with_all_kinds(FakeMemory())
    scripted = [
        (["확인할게요. "], FakeMessage([ToolUseBlock("t1", "get_time", {})], "tool_use")),
        (["지금은 오후 3시입니다."], FakeMessage([TextBlock("지금은 오후 3시입니다.")], "end_turn")),
    ]
    client = FakeAnthropic(scripted)
    prompts = []

    async def confirm(prompt):
        prompts.append(prompt)
        return True

    brain = Brain(FakeSettings(), FakeMemory(), _PERSONA, client=client, registry=reg, confirm=confirm)
    out = _collect(brain, "지금 몇 시야?")
    assert out[0] == TASK_FILLER
    assert "오후 3시" in "".join(out)
    assert prompts == []  # get_time is not gated
    tool_result = client.messages.calls[1]["messages"][-1]["content"][0]
    assert tool_result["tool_use_id"] == "t1" and "시" in tool_result["content"]


def test_irreversible_tool_is_voice_gated():
    reg = _registry_with_all_kinds(FakeMemory())
    scripted = [
        ([], FakeMessage([ToolUseBlock("p1", "premiere_add_clip", {"clip": "a"})], "tool_use")),
        (["타임라인에 적용했습니다."], FakeMessage([TextBlock("타임라인에 적용했습니다.")], "end_turn")),
    ]
    client = FakeAnthropic(scripted)
    prompts = []

    async def confirm(prompt):
        prompts.append(prompt)
        return True

    brain = Brain(FakeSettings(), FakeMemory(), _PERSONA, client=client, registry=reg, confirm=confirm)
    out = _collect(brain, "프리미어에 클립 추가 실행해줘")
    assert len(prompts) == 1 and "premiere_add_clip" in prompts[0]
    tool_result = client.messages.calls[1]["messages"][-1]["content"][0]
    assert "ok" in tool_result["content"]
    assert out[0] == TASK_FILLER
    assert "".join(out[1:]) == "타임라인에 적용했습니다."


def test_calc_and_remember_end_to_end():
    # Spec acceptance: "3 더하기 5 알려주고 메모해줘" -> calc(=8) + remember, one turn.
    memory = FakeMemory()
    reg = _registry_with_all_kinds(memory)
    scripted = [
        (
            [],
            FakeMessage(
                [
                    ToolUseBlock("c1", "calc", {"expression": "3 + 5"}),
                    ToolUseBlock("r1", "remember", {"note": "3 더하기 5는 8"}),
                ],
                "tool_use",
            ),
        ),
        (["3 더하기 5는 8입니다. 메모했습니다."],
         FakeMessage([TextBlock("3 더하기 5는 8입니다. 메모했습니다.")], "end_turn")),
    ]
    client = FakeAnthropic(scripted)

    async def confirm(prompt):
        return True

    brain = Brain(FakeSettings(), memory, _PERSONA, client=client, registry=reg, confirm=confirm)
    out = _collect(brain, "3 더하기 5 알려주고 메모해줘")
    assert out[0] == TASK_FILLER
    assert "8" in "".join(out)
    assert memory.notes == ["3 더하기 5는 8"]
    results = client.messages.calls[1]["messages"][-1]["content"]
    contents = " ".join(r["content"] for r in results)
    assert "8" in contents and "기억" in contents
```

- [ ] **Step 2: Run the integration test — expected GREEN (composition gate, not a unit red phase).**
```bash
~/jarvis/.venv/bin/python -m pytest tests/integration/test_tool_gating.py -q
```
Expected: `4 passed`. (All dependencies were built in Tasks 1–8 with genuine red→green there; this test verifies they compose. There is no honest "module missing" red to claim at this stage.)

- [ ] **Step 3: Create the live-API manual check script (full code).** Create `~/jarvis/scripts/manual_tool_check.py`:
```python
"""Manual M3 live-API check (NOT a pytest — hits the real Claude API).

Two scenarios against the real claude-opus-4-8 TASK path:
  1) "지금 몇 시야?"            -> get_time dispatched, Korean time spoken (acceptance #1)
  2) "3 더하기 5 알려주고 메모해줘" -> calc(=8) + remember dispatched, spoken answer

Run:
    ~/jarvis/.venv/bin/python ~/jarvis/scripts/manual_tool_check.py
"""
import asyncio

import keyring
from anthropic import AsyncAnthropic

from jarvis.brain.claude import Brain
from jarvis.brain.persona import load_persona
from jarvis.core.config import Settings
from jarvis.tools.builtin.local_tools import calc, make_remember_tool
from jarvis.tools.builtin.time_weather import get_time, get_weather
from jarvis.tools.builtin.web_search import WEB_SEARCH_TOOL
from jarvis.tools.registry import ToolRegistry


class _Memory:
    def __init__(self) -> None:
        self.notes: list[str] = []

    def text(self) -> str:
        return "사용자 이름은 이성재. 한국어로 답한다."

    def remember(self, note: str) -> None:
        self.notes.append(note)
        print(f"[REMEMBER] {note!r}")


async def _confirm(prompt: str) -> bool:
    print(f"[VOICE-CONFIRM] {prompt} -> auto-YES")
    return True


async def _run(brain: Brain, registry: ToolRegistry, user_text: str) -> None:
    original = registry.dispatch

    async def traced(name, args):
        print(f"[DISPATCH] {name}({args})")
        return await original(name, args)

    registry.dispatch = traced  # type: ignore[assignment]
    print(f"\nUSER: {user_text}")
    print("JARVIS: ", end="", flush=True)
    async for delta in brain.respond(user_text):
        print(delta, end="", flush=True)
    print()
    registry.dispatch = original  # type: ignore[assignment]


async def main() -> None:
    settings = Settings()
    api_key = keyring.get_password("jarvis", "anthropic_api_key")
    client = AsyncAnthropic(api_key=api_key)
    persona = load_persona(settings.persona_path)
    memory = _Memory()

    registry = ToolRegistry()
    registry.register(get_time)
    registry.register(get_weather)
    registry.register(WEB_SEARCH_TOOL)
    registry.register(make_remember_tool(memory))
    registry.register(calc)

    brain = Brain(settings, memory, persona, client=client, registry=registry, confirm=_confirm)

    await _run(brain, registry, "지금 몇 시야?")
    await _run(brain, registry, "3 더하기 5 알려주고 메모해줘")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Manual verification — live API (not a pytest).** With the Anthropic key in keyring and web search enabled in the Console, run:
```bash
~/jarvis/.venv/bin/python ~/jarvis/scripts/manual_tool_check.py
```
Expected observable output:
- Scenario 1: a `[DISPATCH] get_time({})` line, then a Korean sentence beginning with the `잠시만요` filler and containing the current KST time (e.g. `JARVIS: 잠시만요. ... 지금은 2026년 6월 9일 ... 시 ... 분입니다.`). No `[VOICE-CONFIRM]` line (get_time is not gated).
- Scenario 2: a `[DISPATCH] calc({'expression': '3 + 5'})` line and a `[DISPATCH] remember(...)` + `[REMEMBER]` line, then a Korean answer containing `8`.

This confirms acceptances #1 and #3 against the real `claude-opus-4-8` task path with `thinking={"type":"adaptive"}` + `output_config={"effort":"high"}`.

- [ ] **Step 5: Run the full M3 suite & commit.**
```bash
~/jarvis/.venv/bin/python -m pytest tests/tools tests/brain tests/test_brain.py tests/integration tests/test_main_wiring.py -q
git -C ~/jarvis add tests/integration/test_tool_gating.py scripts/manual_tool_check.py
git -C ~/jarvis commit -m "M3 Task9: integration (heterogeneous tools, gating, calc+memo) + live-API manual check"
```
Expected: full suite green — `40 passed` (Task1 4 + Task2 3 + Task3 4 + Task4 2 + Task5 6 + Task6 5 = 24 under tests/tools; Task7 7 under tests/brain; migrated M1 tests/test_brain.py 2; Task9 4 under tests/integration; Task8 3 under tests/test_main_wiring.py = 40).
