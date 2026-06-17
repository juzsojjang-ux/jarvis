"""백그라운드 자율 작업 — "뒤에서 조사해놔"를 진짜로 뒤에서 한다.

도구(background_task)가 작업을 등록하면 매니저가 별도 두뇌 인스턴스로
asyncio 태스크를 돌리고, 끝나면 on_done 콜백(오케스트레이터: 능동 보고 +
패널 + ~/.jarvis/tasks/ 파일 저장)이 불린다. 전경 대화는 전혀 막지 않는다.

notice_bus와 같은 모듈 싱글턴 브릿지 패턴 — 도구는 start()/status_text()만
부르고, 실제 두뇌 실행은 오케스트레이터가 configure()로 주입한다.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

MAX_CONCURRENT = 2


@dataclass
class BgTask:
    id: int
    desc: str
    status: str = "running"          # running | done | failed
    result: str = ""
    started: str = field(default_factory=lambda: datetime.now().strftime("%H:%M"))


class BgTaskManager:
    def __init__(self, runner: Callable[[str], Any], on_done: Callable[[BgTask], Any],
                 max_concurrent: int = MAX_CONCURRENT):
        self._runner = runner          # async (desc) -> 결과 문자열
        self._on_done = on_done        # async (BgTask) -> None
        self._max = max_concurrent
        self._tasks: list[BgTask] = []
        self._futures: list[asyncio.Task] = []
        self._seq = 0                  # id 카운터 — 이력 pruning과 무관하게 단조 증가

    _HISTORY_CAP = 50                  # 완료 작업 이력 상한

    def running_count(self) -> int:
        return sum(1 for t in self._tasks if t.status == "running")

    def _prune(self) -> None:
        # 완료된 future 제거 + 완료 작업 이력 상한 — append-only로 무한 증가하던 것 방지
        # (audit r3 low). running 작업은 절대 prune하지 않는다.
        self._futures = [f for f in self._futures if not f.done()]
        done = [t for t in self._tasks if t.status != "running"]
        if len(done) > self._HISTORY_CAP:
            drop = {id(t) for t in done[:-self._HISTORY_CAP]}
            self._tasks = [t for t in self._tasks if id(t) not in drop]

    def start(self, desc: str) -> str:
        desc = (desc or "").strip()
        if not desc:
            return "무엇을 해둘지 알려주세요."
        if self.running_count() >= self._max:
            n = self.running_count()
            return f"이미 백그라운드 작업 {n}개가 돌고 있습니다 — 끝나면 시켜주세요."
        self._prune()
        self._seq += 1
        task = BgTask(id=self._seq, desc=desc)
        self._tasks.append(task)
        fut = asyncio.get_running_loop().create_task(self._run(task))
        self._futures.append(fut)
        return f"백그라운드 작업 #{task.id}을 시작했습니다 — 끝나면 보고드리겠습니다."

    async def _run(self, task: BgTask) -> None:
        try:
            out = await self._runner(task.desc)
            task.result = (out or "").strip() or "(결과 없음)"
            task.status = "done"
        except Exception as exc:  # noqa: BLE001 - 작업 실패도 보고 대상이지 크래시가 아니다
            task.result = f"실패: {str(exc)[:200]}"
            task.status = "failed"
        try:
            await self._on_done(task)
        except Exception:  # noqa: BLE001 - 보고 실패가 매니저를 죽이면 안 된다
            pass

    def status_text(self) -> str:
        if not self._tasks:
            return "백그라운드 작업이 없습니다."
        lines = []
        for t in self._tasks[-8:]:
            mark = {"running": "⏳", "done": "✓", "failed": "✗"}[t.status]
            lines.append(f"{mark} #{t.id} ({t.started}) {t.desc[:60]}"
                         + (f" — {t.result[:80]}" if t.status != "running" else ""))
        return "\n".join(lines)


_manager: BgTaskManager | None = None


def configure(runner, on_done, max_concurrent: int = MAX_CONCURRENT) -> None:
    global _manager
    _manager = BgTaskManager(runner, on_done, max_concurrent)


def start(desc: str) -> str:
    if _manager is None:
        return "지금은 백그라운드 작업을 시작할 수 없습니다(부팅 중이거나 비활성)."
    try:
        return _manager.start(desc)
    except RuntimeError:
        return "지금은 백그라운드 작업을 시작할 수 없습니다(이벤트 루프 없음)."


def status_text() -> str:
    if _manager is None:
        return "백그라운드 작업이 없습니다."
    return _manager.status_text()
