"""능동 알림 엔진: 감시자 폴링 → 우선순위 큐 → IDLE일 때 두뇌로 전달.
감시자 하나의 예외는 그 감시자의 이번 폴링만 버린다(웨이크 루프와 같은 원칙 —
1단계에서 VAD 예외 한 번에 웨이크가 영구 침묵한 버그의 재발 방지).
전달 정책: 만료 폐기, kind별 쿨다운, briefing이 boot_greet를 대체."""
from __future__ import annotations

import asyncio
import time

from .events import Announcement


class ProactiveEngine:
    def __init__(self, monitors, *, announce, can_speak,
                 clock=time.monotonic, cooldown_s: float = 600.0,
                 tick_s: float = 1.0,
                 cooldown_overrides: dict[str, float] | None = None):
        self._monitors = list(monitors)
        self._announce = announce          # async (prompt) -> None
        self._can_speak = can_speak        # () -> bool
        # 두-시계 계약: clock(주입)은 알림의 '의미 시간'(만료·쿨다운·created_at)만
        # 지배한다. 폴링 주기는 항상 실제 time.monotonic() — _poll_due_monitors 참조.
        # 테스트가 의미 시간을 정지시켜도 폴링은 흘러가야 하기 때문. 합치지 말 것.
        self._clock = clock
        self._cooldown_s = cooldown_s
        self._tick_s = tick_s
        # kind별 쿨다운 예외 — 타이머처럼 연속 발생이 정상인 종류는 0으로.
        self._cooldown_overrides = dict(cooldown_overrides or {})
        self._pending: list[Announcement] = []
        self._last_spoken: dict[str, float] = {}
        self._next_poll: dict[int, float] = {}
        self._task: asyncio.Task | None = None

    def enqueue(self, ann: Announcement) -> None:
        if ann.kind == "briefing":
            # 브리핑이 인사를 겸한다 — 대기 중인 부팅 인사는 무의미.
            self._pending = [a for a in self._pending if a.kind != "boot_greet"]
        if any(a.dkey == ann.dkey for a in self._pending):
            return                          # 같은 인스턴스(dedup_key) 중복 대기 금지
        self._pending.append(ann)

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return                          # 이미 도는 중 — 고아 태스크 방지
        self._task = asyncio.create_task(self._loop())

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _poll_due_monitors(self) -> None:
        wall = time.monotonic()           # 폴링 간격은 항상 실제 벽시계로 측정
        due = []
        for idx, mon in enumerate(self._monitors):
            if wall < self._next_poll.get(idx, 0.0):
                continue
            self._next_poll[idx] = wall + getattr(mon, "interval_s", 60.0)
            due.append(mon)
        if not due:
            return

        async def _poll_one(mon):
            try:
                return await asyncio.to_thread(mon.poll)
            except Exception as exc:  # noqa: BLE001 - 감시자 하나가 엔진을 죽이면 안 된다
                print(f"[능동] {type(mon).__name__} 폴링 오류(계속): {exc}")
                return []

        # 동시 폴링 — 느린 osascript 감시자(미리알림/캘린더)가 타이머 폴링을 head-of-line
        # 블록해 타이머 알림이 늦던 것 방지(audit r3). 각 poll은 자기 스레드로 오프로드.
        results = await asyncio.gather(*[_poll_one(m) for m in due])
        for anns in results:
            for a in anns:
                self.enqueue(a)

    def _pick(self) -> Announcement | None:
        now = self._clock()
        self._pending = [a for a in self._pending if not a.expired(now)]
        ready = [a for a in self._pending
                 if now - self._last_spoken.get(a.kind, -1e12)
                 >= self._cooldown_overrides.get(a.kind, self._cooldown_s)]
        if not ready:
            return None
        best = min(ready, key=lambda a: (a.priority, a.created_at))
        self._pending.remove(best)
        return best

    async def _loop(self) -> None:
        try:
            while True:
                await self._poll_due_monitors()
                if self._pending and self._can_speak():
                    ann = self._pick()
                    if ann is not None:
                        self._last_spoken[ann.kind] = self._clock()   # 쿨다운(재시도 스팸 방지)
                        try:
                            await self._announce(ann.prompt)
                        except Exception as exc:  # noqa: BLE001 - 한 건 실패가 엔진을 멈추면 안 된다
                            print(f"[능동] 알림 전달 오류(계속): {exc}")
                            # 중요 알림(priority 0, 예: 배터리 위험)만 만료 전 재큐잉 — 발화 전에
                            # 제거돼 한 번의 announce 예외로 영구 소실하던 것 방지(audit r3 low).
                            # 일반 알림은 드롭(재시도 스팸 방지). 쿨다운은 위에서 이미 적용.
                            if ann.priority <= 0 and not ann.expired(self._clock()):
                                self.enqueue(ann)
                await asyncio.sleep(self._tick_s)
        except asyncio.CancelledError:
            pass
