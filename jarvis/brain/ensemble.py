"""세 두뇌 앙상블 — 깊은 생각이 필요한 턴에서 제미나이·GPT에게 같은 질문을
병렬로 던지고, 메인 두뇌(클로드)가 세 관점을 종합해 하나의 답을 만든다.

"클로드 + 보좌 둘"이 아니라 두뇌 자체의 상향 — 메인이 입과 손(도구·페르소나·맥락)을
맡고, 판단은 셋이 같이 한다. 모드(JARVIS_ENSEMBLE_MODE):
  deep(기본) = 딥씽킹 턴에서 자동 / always = 모든 두뇌 턴 / off = 끔
실패·미연동 보조는 조용히 빠진다 — 앙상블이 턴을 깨는 일은 없다.
"""
from __future__ import annotations

import asyncio
from typing import Any

from .consult import PROVIDERS, _consult_gemini, _consult_gpt, available

_LABEL = {"gemini": "제미나이", "gpt": "GPT"}


def mode(settings: Any = None) -> str:
    import os
    m = (os.environ.get("JARVIS_ENSEMBLE_MODE")
         or getattr(settings, "ensemble_mode", None) or "deep").strip().lower()
    return m if m in ("deep", "always", "off") else "deep"


async def gather_opinions(question: str, *, settings: Any = None,
                          timeout_s: float = 30.0,
                          _impls: dict | None = None) -> list[tuple[str, str]]:
    """가용한 보조 두뇌 전부에 병렬 질의 — [(라벨, 의견)]. 실패는 빠진다."""
    if not (question or "").strip():
        return []
    if settings is None:
        from ..core.config import Settings  # noqa: PLC0415
        settings = Settings()
    impls = _impls or {"gemini": _consult_gemini, "gpt": _consult_gpt}
    avail = available()
    targets = [p for p in PROVIDERS if avail.get(p) and p in impls]
    if not targets:
        return []

    async def _one(p: str) -> tuple[str, str] | None:
        try:
            out = await asyncio.wait_for(impls[p](question, settings), timeout=timeout_s)
            out = (out or "").strip()
            # 키 없음/로그인 안내문은 의견이 아니다 — 앙상블에서 제외
            if not out or "자문 불가" in out:
                return None
            return (_LABEL.get(p, p), out)
        except Exception:  # noqa: BLE001 - 한 보조의 실패가 앙상블을 깨면 안 된다
            return None

    results = await asyncio.gather(*(_one(p) for p in targets))
    return [r for r in results if r is not None]


def format_context(opinions: list[tuple[str, str]]) -> str:
    """메인 두뇌 입력에 끼워 넣을 앙상블 블록. 의견이 없으면 빈 문자열."""
    if not opinions:
        return ""
    lines = ["[앙상블 — 보조 두뇌들의 독립 의견. 비판적으로 검토해 종합하고, 갈리는",
             " 지점은 짧게 출처를 밝혀라(예: '제미나이는 …라고 보지만'). 의견이 틀렸으면",
             " 무시해도 된다.]"]
    for label, text in opinions:
        lines.append(f"({label}) {text}")
    lines.append("[/앙상블]")
    return "\n".join(lines) + "\n\n"
