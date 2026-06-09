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
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
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
