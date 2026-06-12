"""LLM 사용량(토큰) 추적 — 세션 + 누적, ~/.jarvis/usage.json 에 저장.

각 두뇌(브레인)가 한 턴이 끝날 때 `last_usage`(SDK가 준 usage 객체/딕셔너리)를 남기면,
오케스트레이터가 UsageTracker.record() 로 토큰을 누적한다. "사용량" 음성 명령이
summary()를 읽어 준다.

주의: Claude **구독(Pro/Max)**은 플랜 잔여량 자체를 API로 노출하지 않는다 — 그래서
실제 사용 '토큰 수'를 집계해 보여준다(많이 쓸수록 커짐). 제미나이/ GPT도 동일하게
응답의 usage 메타에서 토큰을 뽑는다. usage가 없으면 그 턴은 0으로 친다."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_USAGE_PATH = Path.home() / ".jarvis" / "usage.json"

# 입력/출력 토큰 후보 키 — 프로바이더별 이름이 다르다.
_IN_KEYS = ("input_tokens", "prompt_tokens", "prompt_token_count", "promptTokenCount")
_OUT_KEYS = ("output_tokens", "completion_tokens", "candidates_token_count",
             "candidatesTokenCount")


# 한도/요금 초과·레이트리밋을 가리키는 신호(프로바이더별 메시지가 제각각).
_LIMIT_SIGNS = (
    "rate_limit", "rate limit", "ratelimit", "429", "quota", "insufficient_quota",
    "overloaded", "resource_exhausted", "resource exhausted", "too many requests",
    "limit exceeded", "credit balance", "billing", "usage limit", "exceeded your",
)


def is_limit_error(exc: Any) -> bool:
    """예외가 LLM 한도 초과/레이트리밋/요금 문제인지 방어적으로 판별한다."""
    if exc is None:
        return False
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if status == 429 or str(status) == "429":
        return True
    s = f"{type(exc).__name__} {exc}".lower()
    return any(k in s for k in _LIMIT_SIGNS)


def _pick(src: Any, keys: tuple[str, ...]) -> int:
    for k in keys:
        v = src.get(k) if isinstance(src, dict) else getattr(src, k, None)
        if isinstance(v, int | float) and v:
            return int(v)
    return 0


def extract_tokens(usage: Any) -> tuple[int, int]:
    """다양한 SDK usage 객체/딕셔너리에서 (입력토큰, 출력토큰)을 방어적으로 뽑는다."""
    if usage is None:
        return (0, 0)
    # 제미나이는 response.usage_metadata 에 들어있는 경우가 있다.
    meta = getattr(usage, "usage_metadata", None)
    if meta is not None:
        usage = meta
    in_tok = _pick(usage, _IN_KEYS)
    out_tok = _pick(usage, _OUT_KEYS)
    return (in_tok, out_tok)


class UsageTracker:
    def __init__(self, path: str | os.PathLike[str] = DEFAULT_USAGE_PATH) -> None:
        self.path = Path(os.path.expanduser(str(path)))
        self.session = {"input": 0, "output": 0, "turns": 0}
        self.total = self._load()

    def _load(self) -> dict[str, int]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return {"input": int(data.get("input", 0)),
                    "output": int(data.get("output", 0)),
                    "turns": int(data.get("turns", 0))}
        except (OSError, ValueError, TypeError):
            return {"input": 0, "output": 0, "turns": 0}

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.total), encoding="utf-8")
        except OSError:
            pass  # 사용량 집계가 실패해도 대화를 막지 않는다

    def record(self, usage: Any) -> tuple[int, int]:
        in_tok, out_tok = extract_tokens(usage)
        self.session["input"] += in_tok
        self.session["output"] += out_tok
        self.session["turns"] += 1
        self.total["input"] += in_tok
        self.total["output"] += out_tok
        self.total["turns"] += 1
        self._save()
        return (in_tok, out_tok)

    def summary(self) -> str:
        s, t = self.session, self.total

        def _fmt(n: int) -> str:
            return f"{n:,}"

        return (
            f"이번 세션 입력 {_fmt(s['input'])} · 출력 {_fmt(s['output'])} 토큰"
            f"({s['turns']}턴). 누적 입력 {_fmt(t['input'])} · 출력 {_fmt(t['output'])} 토큰"
            f"({t['turns']}턴)."
        )
