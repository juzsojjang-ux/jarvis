"""FallbackTTS — Pocket 실패 시 edge 폴백(무음 금지) 검증."""
import asyncio

import numpy as np

from jarvis.tts.composite import FallbackTTS


class _OK:
    sample_rate = 24000
    def warm(self): pass
    async def synth(self, t): return np.ones(100, dtype=np.float32)


class _Dead:
    sample_rate = 24000
    def warm(self): pass
    async def synth(self, t): raise EOFError("worker died")


class _Empty:
    sample_rate = 24000
    def warm(self): pass
    async def synth(self, t): return np.zeros(0, dtype=np.float32)


class _Fb:
    sample_rate = 22050
    def __init__(self): self.calls = []
    def warm(self): pass
    async def synth(self, t):
        self.calls.append(t)
        return np.full(50, 0.5, dtype=np.float32)


def test_primary_ok_used():
    fb = _Fb()
    out = asyncio.run(FallbackTTS(_OK(), fb).synth("hi"))
    assert len(out) == 100 and fb.calls == []      # 폴백 미사용


def test_primary_dead_falls_back_and_latches():
    fb = _Fb()
    c = FallbackTTS(_Dead(), fb)
    out = asyncio.run(c.synth("hi"))
    assert len(out) == 50 and fb.calls == ["hi"] and c.sample_rate == 22050
    asyncio.run(c.synth("yo"))                       # 죽은 워커 재시도 안 함(래치)
    assert fb.calls == ["hi", "yo"]


def test_primary_empty_on_nonempty_text_falls_back():
    fb = _Fb()
    out = asyncio.run(FallbackTTS(_Empty(), fb).synth("hello"))
    assert len(out) == 50 and fb.calls == ["hello"]


def test_empty_text_no_fallback():
    fb = _Fb()
    out = asyncio.run(FallbackTTS(_Empty(), fb).synth("   "))
    assert len(out) == 0 and fb.calls == []          # 빈 텍스트는 폴백 안 함
