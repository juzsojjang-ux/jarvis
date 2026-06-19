# JARVIS v3.1 에이전트 토대 (Phase A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 자비스 도구 게이트를 단일 정책 권위로 통합하고(우회 구멍 봉쇄·느슨 정책·파국적 데니리스트), 로컬 플러그인 패스스루와 OS 권한 자가복구를 더해 이후 모든 phase의 안전·확장 토대를 만든다.

**Architecture:** 기존 `jarvis/brain/tool_policy.py`(gemini/openai용 `decide()`)를 풀 도구명 분류 `classify()` + `is_catastrophic()`로 확장해 **단일 정책 권위**로 만든다. 구독 두뇌(`subscription.py`)는 `allowed_tools=[]`로 비워 모든 도구가 `_can_use_tool`(→`gating.gate_decision`)을 거치게 하고(우회 결정적 봉쇄), `PreToolUse` 훅을 파국적 deny 2차 안전망 + 미래 phase 배선으로 추가한다. 권한은 기존 `core/permissions.py`를 마이크 점검 + 런타임 `request_for()`로 확장한다.

**Tech Stack:** Python 3.11, `claude-agent-sdk==0.2.94`(`ClaudeAgentOptions.hooks/plugins`, `HookMatcher`, `PermissionResultAllow/Deny`), pydantic-settings, pyobjc(ApplicationServices/Quartz/AVFoundation), pytest.

## Global Constraints

- Python `>=3.11,<3.12`. ruff line-length 100, target py311.
- **구독-순수:** `ANTHROPIC_API_KEY`를 절대 도입하지 않는다(유료 청구 방지). 본 작업은 API 키 불필요.
- **방어적:** 신규/수정 코드의 어떤 함수도 음성 루프를 깨는 예외를 올리지 않는다(try/except로 감싸고 안전측 폴백). 권한·플러그인 실패는 무해하게 흡수.
- **행동 동등성 우선:** 기존 게이트 동작(원격 차단·발송 확인·전권 게이트·jarvis 읽기 자동허용)을 보존한 위에 델타만 더한다. "느슨" 델타 = 비파괴 Bash·범위 내 Write/Edit를 확인→자동허용.
- 플랫폼: macOS(주) + Windows(권한은 no-op=전부 True).
- 한국어 존댓말(사용자 대면 문자열·문서).
- 커밋 메시지 trailer는 저장소 규약을 따른다(`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` 등).
- 스펙: `docs/superpowers/specs/2026-06-19-jarvis-agentic-substrate-design.md`.

---

### Task 1: tool_policy — tier 분류 `classify()` + 헬퍼

**Files:**
- Modify: `jarvis/brain/tool_policy.py` (기존 `READONLY`/`GUARDED`/`decide` 유지, 추가)
- Test: `tests/brain/test_tool_policy.py` (기존 파일에 추가)

**Interfaces:**
- Consumes: 기존 `READONLY`, `GUARDED` frozenset.
- Produces:
  - tier 상수 `READ="read"`, `LOCAL="local"`, `SEND="send"`, `DELETE="delete"`, `PLUGIN_UNTRUSTED="plugin_untrusted"`, `EXTERNAL_MCP="external_mcp"`
  - `SAFE_BUILTINS: frozenset[str]`
  - `classify(tool_name: str, tool_input: dict, *, bash_auto_allow: bool=True, plugin_servers: frozenset[str]=frozenset(), trusted_servers: frozenset[str]=frozenset()) -> str`
  - `is_destructive_bash(cmd: str) -> bool`, `in_scope(path: str) -> bool`

- [ ] **Step 1: Write the failing test**

`tests/brain/test_tool_policy.py` 끝에 추가:

```python
from jarvis.brain.tool_policy import (
    classify, in_scope, is_destructive_bash,
    READ, LOCAL, SEND, DELETE, PLUGIN_UNTRUSTED, EXTERNAL_MCP,
)


def test_classify_jarvis_read_local_send():
    assert classify("mcp__jarvis__get_time", {}) == READ
    assert classify("mcp__jarvis__set_volume", {"level": 50}) == LOCAL
    assert classify("mcp__jarvis__send_mail", {"to": "a"}) == SEND


def test_classify_builtin_read_and_bash_loose():
    assert classify("Read", {"file_path": "/tmp/x"}) == READ
    assert classify("Bash", {"command": "ls ~/Desktop"}) == LOCAL          # 비파괴 → 느슨 자동허용
    assert classify("Bash", {"command": "rm -rf build"}) == DELETE         # 파괴 → 확인
    assert classify("Bash", {"command": "ls"}, bash_auto_allow=False) == DELETE  # strict 토글


def test_classify_write_scope():
    import os
    inside = os.path.join(os.path.expanduser("~"), "notes.txt")
    assert classify("Write", {"file_path": inside}) == LOCAL
    assert classify("Write", {"file_path": "/etc/hosts"}) == DELETE


def test_classify_external_and_plugin():
    assert classify("mcp__premiere__export", {}) == EXTERNAL_MCP
    assert classify("mcp__notion__write", {}, plugin_servers=frozenset({"notion"})) == PLUGIN_UNTRUSTED
    assert classify("mcp__notion__write", {}, plugin_servers=frozenset({"notion"}),
                    trusted_servers=frozenset({"notion"})) == LOCAL


def test_is_destructive_bash():
    assert is_destructive_bash("rm -rf build") is True
    assert is_destructive_bash("ls ~/Desktop") is False
    assert in_scope(os.path.join(os.path.expanduser("~"), "a")) is True
    assert in_scope("/etc/passwd") is False
```

(파일 상단에 `import os`가 없으면 추가.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/brain/test_tool_policy.py -q`
Expected: FAIL (ImportError: cannot import name 'classify').

- [ ] **Step 3: Write minimal implementation**

`jarvis/brain/tool_policy.py`에 추가(기존 `READONLY`/`GUARDED` 아래):

```python
import os

READ = "read"
LOCAL = "local"
SEND = "send"
DELETE = "delete"
PLUGIN_UNTRUSTED = "plugin_untrusted"
EXTERNAL_MCP = "external_mcp"

SAFE_BUILTINS = frozenset({
    "Read", "Glob", "Grep", "TodoWrite", "WebSearch", "WebFetch", "NotebookRead",
})

_DESTRUCTIVE = ("rm ", "rm\t", "rmdir", " dd ", "mkfs", "shutdown", "reboot",
                "kill ", "killall", "diskutil", "fdisk")


def is_destructive_bash(cmd: str) -> bool:
    low = f" {cmd.strip().lower()} "
    return any(tok in low for tok in _DESTRUCTIVE)


def in_scope(path: str) -> bool:
    if not path:
        return False
    try:
        p = os.path.realpath(os.path.expanduser(path))
    except Exception:  # noqa: BLE001
        return False
    roots = [os.path.realpath(os.path.expanduser("~")),
             os.path.realpath(os.getcwd()),
             os.path.realpath(os.path.expanduser("~/.jarvis"))]
    return any(p == r or p.startswith(r + os.sep) for r in roots)


def classify(tool_name: str, tool_input: dict, *, bash_auto_allow: bool = True,
             plugin_servers: frozenset = frozenset(),
             trusted_servers: frozenset = frozenset()) -> str:
    inp = tool_input or {}
    base = tool_name.split("__")[-1]
    if tool_name.startswith("mcp__jarvis__"):
        if base in GUARDED:
            return SEND
        return READ if base in READONLY else LOCAL
    if tool_name.startswith("mcp__"):
        parts = tool_name.split("__")
        server = parts[1] if len(parts) > 1 else ""
        if server in trusted_servers:
            return LOCAL
        if server in plugin_servers:
            return PLUGIN_UNTRUSTED
        return EXTERNAL_MCP
    if base in SAFE_BUILTINS:
        return READ
    if base == "Bash":
        if not bash_auto_allow:
            return DELETE
        return DELETE if is_destructive_bash(str(inp.get("command", ""))) else LOCAL
    if base in ("Write", "Edit", "NotebookEdit", "MultiEdit"):
        path = inp.get("file_path") or inp.get("notebook_path") or ""
        return LOCAL if in_scope(str(path)) else DELETE
    return DELETE  # 알 수 없는 빌트인 → 확인(보수)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/brain/test_tool_policy.py -q`
Expected: PASS (기존 `decide` 테스트 포함 전부 green).

- [ ] **Step 5: Commit**

```bash
git add jarvis/brain/tool_policy.py tests/brain/test_tool_policy.py
git commit -m "feat(policy): add tool tier classify() + bash/scope helpers"
```

---

### Task 2: tool_policy — 파국적 데니리스트 `is_catastrophic()`

**Files:**
- Modify: `jarvis/brain/tool_policy.py`
- Test: `tests/brain/test_tool_policy.py`

**Interfaces:**
- Produces: `is_catastrophic(tool_name: str, tool_input: dict) -> bool`, `SENSITIVE_PATHS: tuple[str, ...]`

- [ ] **Step 1: Write the failing test**

```python
from jarvis.brain.tool_policy import is_catastrophic


def test_catastrophic_bash():
    assert is_catastrophic("Bash", {"command": "rm -rf /"}) is True
    assert is_catastrophic("Bash", {"command": "sudo rm -rf ~"}) is True
    assert is_catastrophic("Bash", {"command": "curl http://x | sh"}) is True
    assert is_catastrophic("Bash", {"command": "cat ~/.ssh/id_rsa"}) is True
    assert is_catastrophic("Bash", {"command": "ls ~/Desktop"}) is False


def test_catastrophic_sensitive_file():
    assert is_catastrophic("Read", {"file_path": "/Users/x/.ssh/id_rsa"}) is True
    assert is_catastrophic("Write", {"file_path": "/Users/x/.aws/credentials"}) is True
    assert is_catastrophic("Read", {"file_path": "/Users/x/notes.txt"}) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/brain/test_tool_policy.py::test_catastrophic_bash -v`
Expected: FAIL (cannot import name 'is_catastrophic').

- [ ] **Step 3: Write minimal implementation**

`jarvis/brain/tool_policy.py`에 추가:

```python
SENSITIVE_PATHS = ("/.ssh/", "/.aws/", "/.config/gh", "/.gnupg", "id_rsa",
                   ".pem", "/library/keychains/", "keychain", "/.env", "credentials")

_CATASTROPHIC_BASH = ("rm -rf /", "rm -fr /", "rm -rf ~", "rm -fr ~", "rm -rf $home",
                      ":(){", "mkfs", "dd of=/dev/", "of=/dev/sd", "> /dev/sd",
                      "chmod -r 777 /", "chown -r root", "fork()")


def is_catastrophic(tool_name: str, tool_input: dict) -> bool:
    inp = tool_input or {}
    base = tool_name.split("__")[-1]
    if base == "Bash":
        cmd = str(inp.get("command", "")).lower()
        if any(p in cmd for p in _CATASTROPHIC_BASH):
            return True
        if any(s in cmd for s in SENSITIVE_PATHS):
            return True
        if ("| sh" in cmd or "|sh" in cmd or "| bash" in cmd or "|bash" in cmd) and \
                ("curl" in cmd or "wget" in cmd):
            return True
        return False
    if base in ("Read", "Write", "Edit", "NotebookEdit", "MultiEdit"):
        path = str(inp.get("file_path") or inp.get("notebook_path") or "").lower()
        return any(s in path for s in SENSITIVE_PATHS)
    return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/brain/test_tool_policy.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add jarvis/brain/tool_policy.py tests/brain/test_tool_policy.py
git commit -m "feat(policy): add is_catastrophic() deny-list (rm -rf, cred paths, curl|sh)"
```

---

### Task 3: tool_policy — `decide()`를 `classify()` 위로 재구현(타 두뇌 동등성)

**Files:**
- Modify: `jarvis/brain/tool_policy.py` (`decide` 본문)
- Test: `tests/brain/test_tool_policy.py` (기존 decide 테스트가 회귀 가드)

**Interfaces:**
- Consumes: `classify`, `READONLY`, `GUARDED`, `confirm_prompt`.
- Produces: `decide(...)` 동일 시그니처/반환(`(bool, str|None)`).

- [ ] **Step 1: Write the failing test**

기존 `decide` 테스트(`test_remote_allows_readonly_only` 등)가 이미 동등성을 검증한다. 추가로 "느슨"이 decide의 jarvis-이름 경로엔 영향 없음을 고정:

```python
def test_decide_local_jarvis_auto_allows():
    import asyncio
    ok, _ = asyncio.run(decide("open_app", {"app": "Safari"},
                               remote_mode=False, trust_on=False, confirm=None))
    assert ok is True
```

(`from jarvis.brain.tool_policy import decide` 가 파일에 이미 있음.)

- [ ] **Step 2: Run test to verify it fails or passes-by-accident**

Run: `.venv/bin/python -m pytest tests/brain/test_tool_policy.py -q`
Expected: 새 테스트는 현재도 통과할 수 있음(현 decide가 else→allow). 재구현 후에도 전체 green이어야 함 — 이 task의 핵심은 회귀 0.

- [ ] **Step 3: Rewrite `decide` on top of classify**

`jarvis/brain/tool_policy.py`의 `decide` 본문 교체(시그니처 유지):

```python
async def decide(name: str, args: dict, *, remote_mode: bool, trust_on: bool,
                 confirm: Optional[Callable[[str], Awaitable[bool]]]) -> tuple[bool, Optional[str]]:
    """(실행 허용?, 거부 시 두뇌에 돌려줄 한국어 사유). gemini/openai 두뇌용 — 민짜 이름.
    classify를 단일 기준으로 쓰되, 이 두뇌들엔 빌트인/플러그인이 없어 jarvis 등급만 의미."""
    if remote_mode:
        return (True, None) if name in READONLY else (False, "원격에서는 실행할 수 없습니다.")
    if trust_on:
        return True, None
    tier = classify(f"mcp__jarvis__{name}", args)
    if tier == SEND:
        if confirm is None:
            return False, "확인할 수 없어 실행하지 않았습니다."
        ok = await confirm(confirm_prompt(name, args))
        return (True, None) if ok else (False, "사용자가 취소했습니다.")
    return True, None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/brain/test_tool_policy.py tests/brain/test_gemini.py tests/brain/test_openai_brain.py -q`
Expected: PASS (전부 green — gemini/openai 동작 불변).

- [ ] **Step 5: Commit**

```bash
git add jarvis/brain/tool_policy.py tests/brain/test_tool_policy.py
git commit -m "refactor(policy): decide() delegates to classify() (single source, no behavior change)"
```

---

### Task 4: 플러그인 발견·신뢰 `jarvis/tools/plugins.py`

**Files:**
- Create: `jarvis/tools/plugins.py`
- Test: `tests/tools/test_plugins.py`

**Interfaces:**
- Produces:
  - `discover(enabled: bool, path: str|os.PathLike|None=None) -> list[dict]` (`[{"type":"local","path": str}]`)
  - `plugin_servers(path=None) -> set[str]`, `trusted_servers(path=None) -> set[str]`

- [ ] **Step 1: Write the failing test**

```python
import json
from pathlib import Path
from jarvis.tools import plugins


def _make_plugin(root: Path, name: str, server: str):
    d = root / name
    d.mkdir(parents=True)
    (d / ".mcp.json").write_text(json.dumps({"mcpServers": {server: {"command": "x"}}}),
                                 encoding="utf-8")
    return d


def test_discover_disabled_returns_empty(tmp_path):
    _make_plugin(tmp_path, "notion-plugin", "notion")
    assert plugins.discover(False, path=tmp_path) == []


def test_discover_and_servers(tmp_path):
    _make_plugin(tmp_path, "notion-plugin", "notion")
    cfgs = plugins.discover(True, path=tmp_path)
    assert cfgs and cfgs[0]["type"] == "local"
    assert plugins.plugin_servers(path=tmp_path) == {"notion"}
    assert plugins.trusted_servers(path=tmp_path) == set()  # trust.json 없음 → 비신뢰


def test_trust_promotes(tmp_path):
    _make_plugin(tmp_path, "notion-plugin", "notion")
    (tmp_path / "trust.json").write_text(json.dumps({"notion-plugin": True}), encoding="utf-8")
    assert plugins.trusted_servers(path=tmp_path) == {"notion"}


def test_broken_dir_is_safe(tmp_path):
    assert plugins.discover(True, path=tmp_path / "nope") == []
    assert plugins.plugin_servers(path=tmp_path / "nope") == set()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/tools/test_plugins.py -q`
Expected: FAIL (ModuleNotFoundError: jarvis.tools.plugins).

- [ ] **Step 3: Write minimal implementation**

```python
"""로컬 Claude Code 플러그인 발견 + 신뢰 레지스트리.

~/.jarvis/plugins/<name>/ 에 둔 플러그인만 로드한다(마켓플레이스 자동설치 없음 — SDK는
type:"local"만 지원). 제3자 코드이므로 기본 비신뢰: 플러그인이 제공하는 MCP 서버의 도구는
~/.jarvis/plugins/trust.json 에서 {"<plugin-dir>": true} 로 명시 승격하기 전까지 확인을 거친다.
어떤 함수도 예외를 올리지 않는다(플러그인 실패가 부팅/턴을 깨면 안 된다)."""
from __future__ import annotations

import json
import os
from pathlib import Path


def _root(path=None) -> Path:
    return Path(path) if path is not None else Path.home() / ".jarvis" / "plugins"


def discover(enabled: bool, path: str | os.PathLike | None = None) -> list[dict]:
    if not enabled:
        return []
    out: list[dict] = []
    try:
        for d in sorted(_root(path).iterdir()):
            if d.is_dir():
                out.append({"type": "local", "path": str(d)})
    except Exception:  # noqa: BLE001
        return []
    return out


def _servers_of(d: Path) -> set[str]:
    try:
        data = json.loads((d / ".mcp.json").read_text(encoding="utf-8"))
        return set((data.get("mcpServers") or {}).keys())
    except Exception:  # noqa: BLE001
        return set()


def plugin_servers(path=None) -> set[str]:
    servers: set[str] = set()
    try:
        for d in _root(path).iterdir():
            if d.is_dir():
                servers |= _servers_of(d)
    except Exception:  # noqa: BLE001
        pass
    return servers


def _trust_map(path=None) -> dict:
    try:
        return json.loads((_root(path) / "trust.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def trusted_servers(path=None) -> set[str]:
    trust = _trust_map(path)
    out: set[str] = set()
    try:
        for d in _root(path).iterdir():
            if d.is_dir() and trust.get(d.name) is True:
                out |= _servers_of(d)
    except Exception:  # noqa: BLE001
        pass
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/tools/test_plugins.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add jarvis/tools/plugins.py tests/tools/test_plugins.py
git commit -m "feat(plugins): local plugin discovery + trust registry (third-party untrusted by default)"
```

---

### Task 5: config 토글 + 게이트 단일 진입 `jarvis/brain/gating.py`

**Files:**
- Modify: `jarvis/core/config.py:169` (orb_hotkey 아래 추가)
- Create: `jarvis/brain/gating.py`
- Test: `tests/brain/test_gating.py`

**Interfaces:**
- Consumes: `tool_policy.classify/is_catastrophic/confirm_prompt/READONLY/SAFE_BUILTINS/tiers`, `plugins.plugin_servers/trusted_servers`, `control_gate.TRUST_GATE`, brain의 `.remote_mode`/`._settings`/`._confirm`.
- Produces:
  - `gate_decision(brain, tool_name: str, tool_input: dict) -> tuple[bool, str|None]` (async)
  - `build_hooks(brain) -> dict` (`{"PreToolUse": [HookMatcher(hooks=[...])]}`)

- [ ] **Step 1: Add config fields**

`jarvis/core/config.py`의 `orb_hotkey` 줄(169) 바로 아래에 추가:

```python

    # --- v3.1 에이전트 토대 ---
    plugins_enabled: bool = False   # ~/.jarvis/plugins/ 로컬 플러그인 로드(기본 끔)
    bash_auto_allow: bool = True    # 느슨: 비파괴 Bash 자동허용(False=항상 확인)
```

- [ ] **Step 2: Write the failing test**

`tests/brain/test_gating.py`:

```python
import asyncio
from jarvis.brain import gating
from jarvis.core.control_gate import TRUST_GATE


class _Settings:
    bash_auto_allow = True


class _Brain:
    def __init__(self, confirm=None, remote=False):
        self._settings = _Settings()
        self._confirm = confirm
        self.remote_mode = remote


def _go(brain, name, inp):
    return asyncio.run(gating.gate_decision(brain, name, inp))


def test_read_and_local_auto_allow():
    b = _Brain(confirm=None)
    assert _go(b, "mcp__jarvis__get_time", {})[0] is True
    assert _go(b, "Bash", {"command": "ls"})[0] is True            # 느슨


def test_catastrophic_denied_even_with_confirm():
    async def yes(p): return True
    ok, why = _go(_Brain(confirm=yes), "Bash", {"command": "rm -rf /"})
    assert ok is False and "안전" in why


def test_send_requires_confirm():
    asked = []
    async def yes(p): asked.append(p); return True
    ok, _ = _go(_Brain(confirm=yes), "mcp__jarvis__send_mail", {"to": "a", "subject": "s"})
    assert ok is True and asked
    ok2, why2 = _go(_Brain(confirm=None), "mcp__jarvis__send_mail", {"to": "a"})
    assert ok2 is False


def test_remote_blocks_non_readonly():
    b = _Brain(confirm=None, remote=True)
    assert _go(b, "mcp__jarvis__get_time", {})[0] is True
    assert _go(b, "mcp__jarvis__open_app", {"app": "x"})[0] is False


def test_trust_gate_allows():
    TRUST_GATE.enable(5.0)
    try:
        assert _go(_Brain(confirm=None), "Write", {"file_path": "/etc/hosts"})[0] is True
    finally:
        TRUST_GATE.disable()


def test_build_hooks_denies_catastrophic():
    hooks = gating.build_hooks(_Brain())
    cb = hooks["PreToolUse"][0].hooks[0]
    out = asyncio.run(cb({"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}}, "t", {}))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    ok = asyncio.run(cb({"tool_name": "Read", "tool_input": {"file_path": "/tmp/x"}}, "t", {}))
    assert ok == {}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/brain/test_gating.py -q`
Expected: FAIL (ModuleNotFoundError: jarvis.brain.gating).

- [ ] **Step 4: Write minimal implementation**

`jarvis/brain/gating.py`:

```python
"""구독 두뇌 도구 게이트의 단일 진입 — tool_policy를 단일 기준으로 호출한다.

판정 순서: 원격 차단 → 파국적 deny → 전권(TRUST_GATE) → tier 분류(READ/LOCAL=허용,
그 외=음성 확인). _can_use_tool이 이 함수를 호출하고, PreToolUse 훅은 파국적 deny를 2차로
강제(미래 phase의 hooks= 배선 확립). 어떤 경로도 예외를 음성 루프로 올리지 않는다."""
from __future__ import annotations

from typing import Any

from ..core.control_gate import TRUST_GATE
from ..tools import plugins
from . import tool_policy as tp


async def gate_decision(brain: Any, tool_name: str, tool_input: dict) -> tuple[bool, str | None]:
    inp = tool_input or {}
    base = tool_name.split("__")[-1]
    # 1) 원격 턴 — 읽기 전용 허용목록만(현 동작 보존)
    if getattr(brain, "remote_mode", False):
        if tool_name.startswith("mcp__jarvis__") and base in tp.READONLY:
            return True, None
        if "__" not in tool_name and base in tp.SAFE_BUILTINS:
            return True, None
        return False, f"{base}은 원격에서는 실행할 수 없습니다."
    # 2) 파국적 데니리스트 — 무조건 차단
    if tp.is_catastrophic(tool_name, inp):
        return False, f"{base}은 안전상 차단했습니다."
    # 3) 전권 위임
    if TRUST_GATE.is_on():
        return True, None
    # 4) tier 분류
    settings = getattr(brain, "_settings", None)
    tier = tp.classify(
        tool_name, inp,
        bash_auto_allow=bool(getattr(settings, "bash_auto_allow", True)),
        plugin_servers=frozenset(plugins.plugin_servers()),
        trusted_servers=frozenset(plugins.trusted_servers()),
    )
    if tier in (tp.READ, tp.LOCAL):
        return True, None
    confirm = getattr(brain, "_confirm", None)
    if confirm is None:
        return False, f"{base}은 음성 확인이 필요합니다."
    ok = await confirm(tp.confirm_prompt(base, dict(inp)))
    return (True, None) if ok else (False, f"{base} 작업을 취소했습니다.")


def build_hooks(brain: Any) -> dict:
    async def pre_tool_use(input: dict, tool_use_id, context):  # noqa: A002
        try:
            name = input.get("tool_name", "")
            inp = input.get("tool_input", {}) or {}
            if tp.is_catastrophic(name, inp):
                return {"hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": f"{name.split('__')[-1]}은 안전상 차단했습니다.",
                }}
        except Exception:  # noqa: BLE001 - 훅 오류가 턴을 깨면 안 된다
            pass
        return {}

    from claude_agent_sdk import HookMatcher
    return {"PreToolUse": [HookMatcher(hooks=[pre_tool_use])]}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/brain/test_gating.py tests/test_config.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add jarvis/brain/gating.py jarvis/core/config.py tests/brain/test_gating.py
git commit -m "feat(gating): single-authority gate_decision + PreToolUse catastrophic hook + config toggles"
```

---

### Task 6: subscription.py 배선 — 우회 봉쇄 + 훅/플러그인 + 위임

**Files:**
- Modify: `jarvis/brain/subscription.py` (`_options` 355-376, `_can_use_tool` 254-284)
- Test: `tests/brain/test_can_use_tool.py` (기존 — "느슨"으로 갱신)

**Interfaces:**
- Consumes: `gating.gate_decision`, `gating.build_hooks`, `plugins.discover`.
- Produces: `_can_use_tool`(시그니처·반환 타입 불변: `PermissionResultAllow/Deny`).

- [ ] **Step 1: Update the gate test for the loose posture**

`tests/brain/test_can_use_tool.py`의 `test_destructive_tool_allowed_on_yes`를 교체(이제 `ls`는 확인 없이 자동허용), 그리고 느슨/데니리스트 케이스 추가:

```python
def test_nondestructive_bash_auto_allows_loose():
    brain = _brain(confirm=None)               # confirm 없어도
    assert _decide(brain, "Bash", {"command": "ls ~/Desktop"}).behavior == "allow"


def test_inscope_write_auto_allows_loose():
    import os
    brain = _brain(confirm=None)
    inside = os.path.join(os.path.expanduser("~"), "note.txt")
    assert _decide(brain, "Write", {"file_path": inside}).behavior == "allow"


def test_catastrophic_denied_even_with_confirm():
    async def yes(p): return True
    brain = _brain(confirm=yes)
    assert _decide(brain, "Bash", {"command": "rm -rf /"}).behavior == "deny"
    assert _decide(brain, "Read", {"file_path": "/Users/x/.ssh/id_rsa"}).behavior == "deny"
```

(기존 `test_readonly_tools_auto_allowed`, `test_destructive_tool_denied_without_confirm`[rm -rf x → DELETE→confirm None→deny], `test_jarvis_mcp_tools_auto_allowed`는 그대로 통과. 기존 `test_destructive_tool_allowed_on_yes`는 삭제/대체.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/brain/test_can_use_tool.py -q`
Expected: FAIL (새 느슨 케이스가 현 인라인 게이트에선 confirm을 요구 → 불일치).

- [ ] **Step 3: Rewire `_options` and `_can_use_tool`**

`jarvis/brain/subscription.py` `_options`에서 `allowed_tools`를 비우고 `plugins`/`hooks` 추가(355-376 구간):

```python
        mcp_servers: dict[str, Any] = {"jarvis": build_jarvis_mcp_server(self._memory)}
        mcp_servers.update(load_external_servers())
        from jarvis.tools.plugins import discover as _discover_plugins
        from .gating import build_hooks
        kw: dict[str, Any] = dict(
            system_prompt=self._system_prompt_arg(),
            # 모든 도구가 _can_use_tool(단일 게이트)을 거치도록 allowed_tools를 비운다 —
            # 읽기 빌트인이 게이트를 우회하던 구멍을 결정적으로 봉쇄(READ 등급이라 자동허용).
            allowed_tools=[],
            can_use_tool=self._can_use_tool,
            mcp_servers=mcp_servers,
            plugins=_discover_plugins(getattr(self._settings, "plugins_enabled", False)),
            hooks=build_hooks(self),
            setting_sources=[],
            cwd=str(Path.home()),
            max_turns=100,
            max_thinking_tokens=thinking_tokens,
            env=env,
            include_partial_messages=True,
        )
        if model:
            kw["model"] = model
        return self._options_cls(**kw)
```

`_can_use_tool` 본문 교체(254-284):

```python
    async def _can_use_tool(self, tool_name, tool_input, context):
        from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny
        from .gating import gate_decision
        ok, why = await gate_decision(self, tool_name, dict(tool_input or {}))
        if ok:
            return PermissionResultAllow()
        return PermissionResultDeny(message=why or "실행하지 않았습니다.")
```

이제 쓰이지 않는 `_SAFE_TOOLS`/`_GUARDED_JARVIS`/`_REMOTE_SAFE_JARVIS`/`_confirm_prompt`는 제거하거나, 다른 곳에서 참조가 없으면 정리한다. **삭제 전 확인:** `grep -rn "_SAFE_TOOLS\|_GUARDED_JARVIS\|_REMOTE_SAFE_JARVIS\|_confirm_prompt" jarvis tests`. 참조가 있으면 남기고, 없으면 삭제.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/brain/test_can_use_tool.py tests/brain/test_subscription.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add jarvis/brain/subscription.py tests/brain/test_can_use_tool.py
git commit -m "feat(subscription): empty allowed_tools (close bypass) + wire hooks/plugins + delegate gate to gating"
```

---

### Task 7: permissions.py — 마이크 점검 + 런타임 `request_for()`

**Files:**
- Modify: `jarvis/core/permissions.py`
- Test: `tests/core/test_permissions.py` (없으면 생성)

**Interfaces:**
- Produces: `microphone_authorized() -> bool`, `request_for(capability: str, announce=None, clock=...) -> None`, `ensure_permissions` 반환 dict에 `"microphone"` 추가.

- [ ] **Step 1: Write the failing test**

`tests/core/test_permissions.py`:

```python
from jarvis.core import permissions as P


def test_request_for_opens_pane_once(monkeypatch):
    opened = []
    monkeypatch.setattr(P, "_is_mac", lambda: True)
    monkeypatch.setattr(P, "open_settings_pane", lambda anchor: opened.append(anchor))
    t = {"v": 100.0}
    clock = lambda: t["v"]
    P._last_request.clear()
    P.request_for("accessibility", clock=clock)
    P.request_for("accessibility", clock=clock)          # 즉시 반복 → 억제
    assert opened == ["Privacy_Accessibility"]
    t["v"] += 120.0
    P.request_for("accessibility", clock=clock)          # TTL 경과 → 다시
    assert opened == ["Privacy_Accessibility", "Privacy_Accessibility"]


def test_request_for_noop_off_mac(monkeypatch):
    monkeypatch.setattr(P, "_is_mac", lambda: False)
    P._last_request.clear()
    P.request_for("screen")  # 예외 없이 통과


def test_microphone_authorized_off_mac(monkeypatch):
    monkeypatch.setattr(P, "_is_mac", lambda: False)
    assert P.microphone_authorized() is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/core/test_permissions.py -q`
Expected: FAIL (AttributeError: module has no attribute 'request_for').

- [ ] **Step 3: Write minimal implementation**

`jarvis/core/permissions.py`에 추가(상단 `import time` 추가):

```python
def microphone_authorized() -> bool:
    """마이크 권한. notDetermined(0)/authorized(3)는 통과(미정은 sounddevice가 OS 요청).
    denied(2)/restricted(1)만 False. API 불가 시 보수적 True(막지 않음)."""
    if not _is_mac():
        return True
    try:
        from AVFoundation import AVCaptureDevice, AVMediaTypeAudio  # type: ignore
        return AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio) in (0, 3)
    except Exception:  # noqa: BLE001
        return True


_ANCHORS = {"accessibility": "Privacy_Accessibility", "screen": "Privacy_ScreenCapture",
            "input_monitoring": "Privacy_ListenEvent", "microphone": "Privacy_Microphone"}
_MSG = {"accessibility": "화면 제어에는 손쉬운 사용 권한이 필요합니다.",
        "screen": "화면을 보려면 화면 기록 권한이 필요합니다.",
        "input_monitoring": "키 입력에는 입력 모니터링 권한이 필요합니다.",
        "microphone": "음성 인식에는 마이크 권한이 필요합니다."}
_last_request: dict[str, float] = {}
_REQUEST_TTL_S = 60.0


def request_for(capability: str, announce: Callable[[str], None] | None = None,
                clock=time.monotonic) -> None:
    """런타임 권한 막힘 시 — 해당 설정 창을 열고 1회 안내. TTL 내 중복은 억제(잔소리 방지)."""
    if not _is_mac():
        return
    now = clock()
    if now - _last_request.get(capability, -1e9) < _REQUEST_TTL_S:
        return
    _last_request[capability] = now
    anchor = _ANCHORS.get(capability)
    if anchor:
        open_settings_pane(anchor)
    msg = _MSG.get(capability, "권한이 필요합니다.")
    print(f"[권한] ⚠ {msg} 시스템 설정을 열었습니다 — 'JARVIS'를 켜주세요.")
    if announce is not None:
        try:
            announce(msg + " 시스템 설정에서 켜주세요.")
        except Exception:  # noqa: BLE001
            pass
```

그리고 `_ensure_permissions_mac`의 반환 dict에 마이크 추가(기존 `return {...}` 교체):

```python
    mic = microphone_authorized()
    if not mic:
        print("[권한] (참고) 마이크 권한이 꺼져 있습니다 — 음성 인식에 필요합니다.")
    return {"input_monitoring": listen, "accessibility": acc, "screen": scr, "microphone": mic}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/core/test_permissions.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add jarvis/core/permissions.py tests/core/test_permissions.py
git commit -m "feat(permissions): microphone check + runtime request_for() with TTL dedupe"
```

---

### Task 8: 화면 도구 권한 프리체크 → `request_for` (막힐 때 재요청)

**Files:**
- Modify: `jarvis/tools/jarvis_mcp.py` (`_capture_screen` 981, `_screen_control` 997, `_click_by_name` 1011)
- Test: `tests/tools/test_screen_guard.py`

**Interfaces:**
- Consumes: `permissions.accessibility_trusted/screen_capture_trusted/request_for`.
- Produces: `_screen_guard(capability: str) -> str | None` (헬퍼; 권한 OK면 None, 막혔으면 안내 문자열 + `request_for` 호출).

- [ ] **Step 1: Write the failing test**

`tests/tools/test_screen_guard.py`:

```python
from jarvis.tools import jarvis_mcp
from jarvis.core import permissions as P


def test_screen_guard_blocks_and_requests(monkeypatch):
    calls = []
    monkeypatch.setattr(P, "accessibility_trusted", lambda *a, **k: False)
    monkeypatch.setattr(P, "request_for", lambda cap, **k: calls.append(cap))
    msg = jarvis_mcp._screen_guard("accessibility")
    assert msg is not None and "손쉬운 사용" in msg
    assert calls == ["accessibility"]


def test_screen_guard_passes_when_granted(monkeypatch):
    monkeypatch.setattr(P, "screen_capture_trusted", lambda *a, **k: True)
    assert jarvis_mcp._screen_guard("screen") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/tools/test_screen_guard.py -q`
Expected: FAIL (AttributeError: module has no attribute '_screen_guard').

- [ ] **Step 3: Write minimal implementation**

`jarvis/tools/jarvis_mcp.py`에 헬퍼 추가(`_capture_screen` 위):

```python
def _screen_guard(capability: str) -> str | None:
    """TCC 권한 프리체크 — 막혔으면 설정 열고(재요청) 안내 문자열 반환, OK면 None."""
    from jarvis.core import permissions as _P
    ok = _P.screen_capture_trusted() if capability == "screen" else _P.accessibility_trusted()
    if ok:
        return None
    _P.request_for(capability)
    if capability == "screen":
        return "화면 기록 권한이 꺼져 있습니다. 방금 연 시스템 설정에서 JARVIS를 켜고 다시 시도해 주세요."
    return "화면 제어에는 손쉬운 사용 권한이 필요합니다. 방금 연 시스템 설정에서 JARVIS를 켜주세요."
```

세 핸들러 앞에 가드 삽입:

```python
async def _capture_screen(_args):
    g = _screen_guard("screen")
    if g:
        return _text(g)
    return _text(capture_screen_action())


async def _screen_control(args):
    g = _screen_guard("accessibility")
    if g:
        return _text(g)
    a = args or {}
    return _text(screen_control_action(
        str(a.get("action") or ""), a.get("x"), a.get("y"),
        str(a.get("text") or ""), str(a.get("key") or ""), a.get("amount")))


async def _click_by_name(args):
    g = _screen_guard("accessibility")
    if g:
        return _text(g)
    a = args or {}
    return _text(ui_click_action(str(a.get("name", "")), role=str(a.get("role", ""))))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/tools/test_screen_guard.py tests/tools/test_screen.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add jarvis/tools/jarvis_mcp.py tests/tools/test_screen_guard.py
git commit -m "feat(permissions): screen tools preflight TCC + request_for on block (self-healing)"
```

---

### Task 9: 전체 회귀 + 사용설명서 갱신

**Files:**
- Modify: `docs/사용설명서.md`
- Test: 전체 스위트

- [ ] **Step 1: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (실패 시 systematic-debugging으로 원인 격리 — 특히 `test_main_wiring.py`, `test_subscription.py`, `tests/tools/test_send.py`, `tests/remote/` 회귀 확인).

- [ ] **Step 2: ruff 정리**

Run: `.venv/bin/ruff check jarvis/brain/tool_policy.py jarvis/brain/gating.py jarvis/tools/plugins.py jarvis/core/permissions.py jarvis/brain/subscription.py jarvis/tools/jarvis_mcp.py`
Expected: clean(또는 자동수정 `ruff check --fix`).

- [ ] **Step 3: 사용설명서 갱신**

`docs/사용설명서.md`에 v3.1 항목 추가(기존 changelog/섹션 패턴 따름):
- **보안 게이트(느슨):** 로컬에선 대부분 자동 실행, 외부 발송·삭제만 확인. `rm -rf /`·자격증명 경로 등 파국적 명령은 항상 차단.
- **`bash_auto_allow` 토글:** 끄면(`JARVIS_BASH_AUTO_ALLOW=0` 또는 설정 파일) 모든 셸 명령을 매번 확인.
- **플러그인:** `~/.jarvis/plugins/<이름>/`에 Claude Code 플러그인을 두고 `plugins_enabled`(`JARVIS_PLUGINS_ENABLED=1`)로 켠다. 제3자라 기본 비신뢰 — `~/.jarvis/plugins/trust.json`에 `{"<이름>": true}`로 명시해야 자동 실행. (자동 다운로드는 다음 버전)
- **권한 자가복구:** 시작 시 손쉬운 사용·입력 모니터링·화면 기록·마이크를 점검해 꺼져 있으면 설정을 열어 안내. 화면 제어/캡처가 권한에 막히면 그 순간 설정을 열어 재요청.

- [ ] **Step 4: Commit**

```bash
git add docs/사용설명서.md
git commit -m "docs: v3.1 agentic substrate (loose gate, plugins, permission self-healing)"
```

---

## Self-Review (작성자 체크)

**Spec coverage:** §3 확장/신규/수정 → T1-3(tool_policy)·T4(plugins)·T5(gating+config)·T6(subscription)·T7-8(permissions)·T9(docs). §4 게이트 흐름 → T5 gate_decision + T6 위임. §4 우회 봉쇄 → T6 `allowed_tools=[]`. §5 플러그인 → T4 + T6 wiring. §6.1 마이크 → T7. §6.2 막힐때 → T7 request_for + T8 화면 도구. §11 테스트 → 각 task TDD. 모든 스펙 요구에 대응 task 존재. ✅

**Placeholder scan:** "TBD"/"적절히 처리"/추상 단계 없음 — 모든 코드 단계에 실제 코드. ✅

**Type consistency:** tier 상수(READ/LOCAL/SEND/DELETE/PLUGIN_UNTRUSTED/EXTERNAL_MCP)·함수명(`classify`/`is_catastrophic`/`gate_decision`/`build_hooks`/`discover`/`plugin_servers`/`trusted_servers`/`request_for`/`microphone_authorized`/`_screen_guard`)이 정의 task와 소비 task에서 일치. `gate_decision`은 brain의 `_settings`/`remote_mode`/`_confirm`(subscription.py 실측 확인)만 의존. ✅

**미검증 가정(스펙 §9):** `HookMatcher(matcher 미지정)=전체 매칭`, 빈 `allowed_tools`+`can_use_tool` 조합에서 모든 도구가 `_can_use_tool`을 거침, 훅 콜백 내 `await _confirm` 대기 — Task 5/6 통과 후 `claude_agent_sdk/testing` 또는 실기동 스모크로 확인(T9 Step 1에서 회귀 포함).
