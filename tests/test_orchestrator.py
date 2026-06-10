import asyncio

import numpy as np

from jarvis.brain.sentence import SentenceChunker
from jarvis.core.config import Settings
from jarvis.core.events import State
from jarvis.core.orchestrator import Orchestrator


class _FakeSTT:
    def transcribe(self, pcm, sample_rate=16000, language="ko"):
        return "안녕하세요. 무엇을 도와드릴까요?"


class _FakeBrain:
    async def respond(self, user_text):
        for d in ["안녕하", "세요. 무엇을 ", "도와드릴까요?"]:
            yield d


class _FakeTTS:
    def __init__(self):
        self.sample_rate = 22050

    async def synth(self, text):
        return np.ones(220, dtype=np.float32) * 0.1


class _FakeVC:
    def __init__(self):
        self.sample_rate = 22050

    def convert(self, pcm, in_rate):
        self.sample_rate = in_rate
        return np.asarray(pcm, dtype=np.float32)


class _FakePlayback:
    def __init__(self):
        self.sample_rate = 48000
        self.feeds = []
        self.aborted = 0

    def start(self):
        pass

    def feed(self, pcm):
        self.feeds.append(np.asarray(pcm))

    def abort(self):
        self.aborted += 1


class _FakeActivator:
    def start(self, on_press, on_release):
        pass

    def stop(self):
        pass


def _make(playback=None):
    pb = playback or _FakePlayback()
    return Orchestrator(
        settings=Settings(),
        activator=_FakeActivator(),
        capture=None,
        stt=_FakeSTT(),
        brain=_FakeBrain(),
        chunker=SentenceChunker(),
        tts=_FakeTTS(),
        vc=_FakeVC(),
        playback=pb,
    ), pb


def test_pipeline_feeds_playback_at_48k_float32():
    orch, pb = _make()
    asyncio.run(orch._pipeline(np.zeros(16000, dtype=np.float32)))
    assert len(pb.feeds) >= 2  # two sentences -> two TTS chunks
    for f in pb.feeds:
        assert f.dtype == np.float32
        assert len(f) > 0  # 220 @ 22050 -> ~480 @ 48000
    assert orch.state == State.IDLE


def test_speak_skips_empty_sentence():
    # empty/whitespace must NOT reach TTS/VC (it crashes RVC -> silent dead turn)
    orch, pb = _make()
    asyncio.run(orch._speak("   "))
    assert pb.feeds == []


def test_speak_falls_back_to_base_voice_when_vc_fails():
    class _BoomVC:
        sample_rate = 22050

        def convert(self, pcm, in_rate):
            raise RuntimeError("rvc boom")

    orch, pb = _make()
    orch.vc = _BoomVC()
    asyncio.run(orch._speak("안녕하세요"))
    assert len(pb.feeds) == 1 and pb.feeds[0].dtype == np.float32  # heard, not silent


def test_barge_in_cancels_brain_task_and_aborts_playback():
    orch, pb = _make()

    async def run():
        async def long_pipeline():
            await asyncio.sleep(5)

        orch._task = asyncio.create_task(long_pipeline())
        t = orch._task  # capture before _cancel_pipeline() clears orch._task
        await asyncio.sleep(0)  # let it start
        await orch._cancel_pipeline()
        return t

    task = asyncio.run(run())
    assert task.cancelled()
    assert pb.aborted == 1
    assert orch.state == State.IDLE
