"""HUD 우측 정보 패널의 전역 싱크 — 두뇌 도구(show_panel/hide_panel)가
오케스트레이터의 HUD에 닿게 하는 가벼운 브릿지.

오케스트레이터가 시작 시 ``set_sink(self._notify)`` 로 자기 알림 함수를 건다.
도구는 ``show(text)`` / ``hide()`` 만 호출하면 되고, 실제 표시·음소거 판단은
오케스트레이터의 _notify가 한다(패널 끄기 상태면 억제). 싱크가 없으면(테스트/
HUD 비활성) 조용히 False를 돌려준다 — 도구가 깨지지 않는다."""
from __future__ import annotations

from collections.abc import Callable

_sink: Callable[[str], None] | None = None


def set_sink(fn: Callable[[str], None] | None) -> None:
    global _sink
    _sink = fn


def show(text: str) -> bool:
    if _sink is None:
        return False
    try:
        _sink(text or "")
        return True
    except Exception:  # noqa: BLE001 - 패널 표시 실패가 도구를 깨면 안 된다
        return False


def hide() -> bool:
    return show("")
