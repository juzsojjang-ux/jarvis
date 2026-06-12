"""Gemini/GPT 두뇌용 도구 권한 정책 — 민짜 도구 이름 기준(Claude 게이트와 별개).
원격=읽기전용, 전권=전부, 발송=확인, 그 외=자동 허용(로컬 사용자 현장)."""
from __future__ import annotations

from typing import Awaitable, Callable, Optional

READONLY = frozenset({
    "get_time", "get_weather", "battery_status", "get_reminders",
    "get_calendar_events", "list_timers", "get_messages", "get_unread_mail",
    "clipboard_read", "remember",
    "self_check", "consult_brain",  # 읽기·자문 전용 — 기기 부작용 없음
})
GUARDED = frozenset({"send_message", "send_mail"})


def confirm_prompt(name: str, args: dict) -> str:
    a = args or {}
    if name == "send_message":
        r = str(a.get("recipient", "")); t = str(a.get("text", ""))[:40]
        return f"{r}에게 '{t}' 보낼까요?"
    if name == "send_mail":
        to = str(a.get("to", "")); s = str(a.get("subject", ""))
        return f"{to}에게 '{s}' 메일 보낼까요?"
    return f"{name} 작업을 실행할까요?"


async def decide(name: str, args: dict, *, remote_mode: bool, trust_on: bool,
                 confirm: Optional[Callable[[str], Awaitable[bool]]]) -> tuple[bool, Optional[str]]:
    """(실행 허용?, 거부 시 두뇌에 돌려줄 한국어 사유)."""
    if remote_mode:
        if name in READONLY:
            return True, None
        return False, "원격에서는 실행할 수 없습니다."
    if trust_on:
        return True, None
    if name in GUARDED:
        if confirm is None:
            return False, "확인할 수 없어 실행하지 않았습니다."
        ok = await confirm(confirm_prompt(name, args))
        return (True, None) if ok else (False, "사용자가 취소했습니다.")
    return True, None
