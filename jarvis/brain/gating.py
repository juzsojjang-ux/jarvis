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
    try:
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
    except Exception as exc:  # noqa: BLE001
        try:
            print(f"[게이트] 판정 오류(차단): {exc}")
        except Exception:  # noqa: BLE001
            pass
        return False, "게이트 확인 중 오류가 발생했습니다."


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
