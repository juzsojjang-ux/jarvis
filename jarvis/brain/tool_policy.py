"""Gemini/GPT 두뇌용 도구 권한 정책 — 민짜 도구 이름 기준(Claude 게이트와 별개).
원격=읽기전용, 전권=전부, 발송=확인, 그 외=자동 허용(로컬 사용자 현장)."""
from __future__ import annotations

import os
import re
from collections.abc import Awaitable, Callable

READONLY = frozenset({
    "get_time", "get_weather", "battery_status", "get_reminders",
    "get_calendar_events", "list_timers", "get_messages", "get_unread_mail",
    "clipboard_read", "remember",
    "self_check", "consult_brain",  # 읽기·자문 전용 — 기기 부작용 없음
    "background_status", "recall_memory", "list_skills",  # 읽기 전용 조회
})
GUARDED = frozenset({"send_message", "send_mail"})


def confirm_prompt(name: str, args: dict) -> str:
    a = args or {}
    if name == "Bash":
        cmd = str(a.get("command", ""))[:80]
        return f"명령을 실행할까요? {cmd}"
    if name in ("Write", "Edit", "NotebookEdit", "MultiEdit"):
        path = a.get("file_path") or a.get("notebook_path") or "파일"
        return f"{path} 파일을 수정할까요?"
    if name == "send_message":
        r = str(a.get("recipient", ""))
        t = str(a.get("text", ""))[:40]
        return f"{r}에게 '{t}' 보낼까요?"
    if name == "send_mail":
        to = str(a.get("to", ""))
        s = str(a.get("subject", ""))
        return f"{to}에게 '{s}' 메일 보낼까요?"
    return f"{name} 작업을 실행할까요?"


async def decide(name: str, args: dict, *, remote_mode: bool, trust_on: bool,
                 confirm: Callable[[str], Awaitable[bool]] | None) -> tuple[bool, str | None]:
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


# ---------------------------------------------------------------------------
# Task 1: tier 상수 + classify() + 헬퍼
# ---------------------------------------------------------------------------

READ = "read"
LOCAL = "local"
SEND = "send"
DELETE = "delete"
PLUGIN_UNTRUSTED = "plugin_untrusted"
EXTERNAL_MCP = "external_mcp"

SAFE_BUILTINS = frozenset({
    "Read", "Glob", "Grep", "TodoWrite", "WebSearch", "WebFetch", "NotebookRead",
})

_DESTRUCTIVE_RE = re.compile(
    r"\b(rm|rmdir|dd|mkfs|shutdown|reboot|kill|killall|diskutil|fdisk)\b"
)


def is_destructive_bash(cmd: str) -> bool:
    return bool(_DESTRUCTIVE_RE.search(cmd.lower()))


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


# ---------------------------------------------------------------------------
# Task 2: 파국적 데니리스트 — 절대 실행 불가
# ---------------------------------------------------------------------------

SENSITIVE_PATHS = ("/.ssh/", "/.aws/", "/.config/gh", "/.gnupg", "id_rsa",
                   ".pem", "/library/keychains/", "keychain", "credentials")


def _is_env_file(token: str) -> bool:
    """Return True for .env / .env.* files (exact basename match, no false positives)."""
    b = os.path.basename(str(token).strip().strip("'\""))
    return b == ".env" or b.startswith(".env.")

_CATASTROPHIC_BASH = ("rm -rf /", "rm -fr /", "rm -rf ~", "rm -fr ~", "rm -rf $home",
                      ":(){", "mkfs", "dd of=/dev/", "of=/dev/sd", "> /dev/sd",
                      "chmod -r 777 /", "chown -r root", "fork()")


def is_catastrophic(tool_name: str, tool_input: dict) -> bool:
    inp = tool_input or {}
    base = str(tool_name or "").split("__")[-1]
    if base == "Bash":
        cmd = " ".join(str(inp.get("command", "")).lower().split())
        if any(p in cmd for p in _CATASTROPHIC_BASH):
            return True
        if any(s in cmd for s in SENSITIVE_PATHS):
            return True
        if any(_is_env_file(tok) for tok in cmd.split()):
            return True
        if ("| sh" in cmd or "|sh" in cmd or "| bash" in cmd or "|bash" in cmd) and \
                ("curl" in cmd or "wget" in cmd):
            return True
        return False
    if base in ("Read", "Write", "Edit", "NotebookEdit", "MultiEdit"):
        path = str(inp.get("file_path") or inp.get("notebook_path") or "").lower()
        return any(s in path for s in SENSITIVE_PATHS) or _is_env_file(path)
    return False
