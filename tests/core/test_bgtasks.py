"""백그라운드 자율 작업 — 등록/완료 보고/실패 격리/동시 한도."""
from __future__ import annotations

import asyncio

from jarvis.core.bgtasks import BgTaskManager


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def test_start_runs_and_reports_done():
    done = []
    async def runner(desc):
        return f"{desc} 결과"
    async def on_done(t):
        done.append(t)
    async def main():
        m = BgTaskManager(runner, on_done)
        msg = m.start("환율 조사")
        assert "#1" in msg and "시작" in msg
        await asyncio.sleep(0.05)
        return m
    m = run(main())
    assert done and done[0].status == "done" and "환율 조사 결과" in done[0].result


def test_failure_isolated_and_reported():
    done = []
    async def runner(desc):
        raise RuntimeError("브라우저 죽음")
    async def on_done(t):
        done.append(t)
    async def main():
        m = BgTaskManager(runner, on_done)
        m.start("작업")
        await asyncio.sleep(0.05)
    run(main())
    assert done and done[0].status == "failed" and "브라우저 죽음" in done[0].result


def test_concurrency_limit():
    async def runner(desc):
        await asyncio.sleep(1)
    async def on_done(t):
        pass
    async def main():
        m = BgTaskManager(runner, on_done, max_concurrent=2)
        assert "시작" in m.start("a")
        assert "시작" in m.start("b")
        msg = m.start("c")
        assert "이미" in msg
    run(main())


def test_status_text_lists_marks():
    async def runner(desc):
        return "ok"
    async def on_done(t):
        pass
    async def main():
        m = BgTaskManager(runner, on_done)
        m.start("뉴스 정리")
        await asyncio.sleep(0.05)
        return m.status_text()
    txt = run(main())
    assert "✓ #1" in txt and "뉴스 정리" in txt


def test_empty_desc_rejected():
    async def main():
        m = BgTaskManager(lambda d: None, lambda t: None)
        return m.start("  ")
    assert "알려주세요" in run(main())


def test_module_start_without_configure_is_safe():
    import jarvis.core.bgtasks as bg
    old = bg._manager
    bg._manager = None
    try:
        assert "없" in bg.status_text() or "없습니다" in bg.status_text()
        assert "수 없습니다" in bg.start("x")
    finally:
        bg._manager = old
