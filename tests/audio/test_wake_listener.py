import asyncio

import numpy as np

from jarvis.audio.utterance import UtteranceDetector
from jarvis.audio.wake import WakeListener


class _FakeMic:
    sample_rate = 16000

    def __init__(self):
        self.cb = None
        self.ensure_calls = 0

    def subscribe(self, cb):
        self.cb = cb

    def unsubscribe(self, cb):
        self.cb = None

    def ensure_running(self):
        self.ensure_calls += 1


class _FakeVAD:
    """말소리 에너지가 있으면 0.9, 없으면 0.05 — 테스트용 결정적 VAD."""

    def prob(self, frame):
        return 0.9 if float(np.max(np.abs(frame))) > 0.01 else 0.05

    def reset(self):
        pass


def _listener():
    mic = _FakeMic()
    det = UtteranceDetector(threshold=0.5, silence_ms=96, min_speech_ms=64,
                            max_s=30.0, pre_roll_ms=64)
    wl = WakeListener(mic, _FakeVAD(), det, poll_s=0.005)
    return mic, wl


def _speech(frames=6):
    return np.full(512 * frames, 0.3, dtype=np.float32)


def _silence(frames=4):
    return np.zeros(512 * frames, dtype=np.float32)


def test_utterance_delivered_when_gate_open():
    mic, wl = _listener()
    got = []

    async def run():
        wl.start(got.append, lambda: True)
        mic.cb(_speech())
        mic.cb(_silence())
        await asyncio.sleep(0.05)
        wl.stop()

    asyncio.run(run())
    assert len(got) == 1
    assert got[0].dtype == np.float32 and len(got[0]) >= 6 * 512
    assert mic.ensure_calls > 0          # 스트림 자동 복구 폴링


def test_gate_closed_drops_partial_audio():
    mic, wl = _listener()
    got = []

    async def run():
        gate = {"open": False}
        wl.start(got.append, lambda: gate["open"])
        mic.cb(_speech())                # 게이트 닫힘(SPEAKING 등) 동안 들어온 소리
        await asyncio.sleep(0.02)
        gate["open"] = True              # 게이트가 열려도 이전 버퍼는 버려졌어야 한다
        mic.cb(_silence())
        await asyncio.sleep(0.05)
        wl.stop()

    asyncio.run(run())
    assert got == []


def test_window_remainder_carries_over():
    mic, wl = _listener()
    got = []

    async def run():
        wl.start(got.append, lambda: True)
        buf = np.concatenate([_speech(), _silence()])
        for i in range(0, len(buf), 700):   # 512와 어긋나는 700샘플 단위로 흘려보냄
            mic.cb(buf[i:i + 700])
        await asyncio.sleep(0.05)
        wl.stop()

    asyncio.run(run())
    assert len(got) == 1
