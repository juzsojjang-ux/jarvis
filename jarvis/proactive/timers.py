"""음성 타이머 보드 — MCP 도구(등록/취소/목록)와 TimerMonitor(만기 수확)가
공유한다. SubscriptionBrain이 build_jarvis_mcp_server(memory)를 직접 만들기
때문에 보드는 모듈 싱글턴(DEFAULT_BOARD)으로 공유한다(서버는 인프로세스 —
같은 객체다). 도구는 asyncio 루프에서, 모니터는 to_thread에서 접근하므로
락으로 보호한다."""
from __future__ import annotations

import itertools
import threading
import time


class TimerBoard:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._seq = itertools.count(1)
        self._timers: dict[int, tuple[str, float]] = {}  # id -> (라벨, 만기시각)

    def add(self, seconds: float, label: str = "") -> tuple[int, str]:
        label = (label or "").strip() or "타이머"
        with self._lock:
            tid = next(self._seq)
            self._timers[tid] = (label, self._clock() + max(1.0, float(seconds)))
        return tid, label

    def cancel(self, label: str = "") -> str:
        """라벨 부분일치 취소. 생략 시: 1개면 그것, 여럿이면 목록 안내."""
        with self._lock:
            if not self._timers:
                return "진행 중인 타이머가 없습니다."
            label = (label or "").strip()
            if not label:
                if len(self._timers) == 1:
                    tid, (lb, _) = next(iter(self._timers.items()))
                    del self._timers[tid]
                    return f"'{lb}' 타이머를 취소했습니다."
                names = ", ".join(lb for lb, _ in self._timers.values())
                return f"타이머가 여러 개입니다({names}) — 어느 것을 취소할까요?"
            for tid, (lb, _) in list(self._timers.items()):
                if label in lb:
                    del self._timers[tid]
                    return f"'{lb}' 타이머를 취소했습니다."
            return f"'{label}' 타이머를 찾지 못했습니다."

    def listing(self) -> list[tuple[str, int]]:
        now = self._clock()
        with self._lock:
            return [(lb, max(0, int(due - now))) for lb, due in self._timers.values()]

    def pop_due(self) -> list[str]:
        """만기된 타이머 라벨을 꺼내고 보드에서 제거(1회성)."""
        now = self._clock()
        out: list[str] = []
        with self._lock:
            for tid, (lb, due) in list(self._timers.items()):
                if now >= due:
                    out.append(lb)
                    del self._timers[tid]
        return out


# 공유 싱글턴 — 배선(__main__)과 jarvis_mcp 기본값이 같은 보드를 쓴다.
DEFAULT_BOARD = TimerBoard()
