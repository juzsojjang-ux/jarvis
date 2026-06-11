"""화면 제어 모드 게이트 — 오케스트레이터(음성 토글)와 jarvis_mcp의 screen_control
도구가 공유한다. SubscriptionBrain이 MCP 서버를 인프로세스로 만들기 때문에
TimerBoard·DEFAULT_BOARD 패턴 그대로 모듈 싱글턴(CONTROL_GATE)으로 공유한다.
도구는 asyncio 루프에서, 토글은 같은 루프지만 to_thread 접근 가능성이 있어
락으로 보호한다. 켠 채 잊는 위험을 막으려고 TTL이 지나면 스스로 꺼진다."""
from __future__ import annotations

import threading
import time


class ControlGate:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._until = 0.0

    def enable(self, ttl_s: float = 300.0) -> None:
        with self._lock:
            self._until = self._clock() + max(1.0, float(ttl_s))

    def disable(self) -> None:
        with self._lock:
            self._until = 0.0

    def is_on(self) -> bool:
        with self._lock:
            return self._clock() < self._until


# 공유 싱글턴 — 오케스트레이터가 토글하고 screen_control 도구가 확인한다.
CONTROL_GATE = ControlGate()
