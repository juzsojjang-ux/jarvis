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


def test_play_ack_speaks_immediately_and_caches():
    orch, pb = _make()
    asyncio.run(orch._play_ack())
    assert len(pb.feeds) == 1 and pb.feeds[0].dtype == np.float32
    assert len(orch._ack_cache) == 1          # first filler synthesised + cached
    asyncio.run(orch._play_ack())             # rotates to the next filler
    assert len(pb.feeds) == 2 and len(orch._ack_cache) == 2


def test_pipeline_emits_ack_before_answer():
    orch, pb = _make()
    asyncio.run(orch._pipeline(np.zeros(16000, dtype=np.float32)))
    # ack + the two answer sentences -> at least three audio chunks fed
    assert len(pb.feeds) >= 3
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


class _WakeSTT:
    def __init__(self, text):
        self.text = text

    def transcribe(self, pcm, sample_rate=16000, language="ko"):
        return self.text


def test_wake_command_runs_pipeline():
    orch, pb = _make()
    orch.stt = _WakeSTT("자비스 지금 몇 시야")

    async def run():
        orch._on_wake_utterance(np.zeros(16000, dtype=np.float32))
        await orch._task

    asyncio.run(run())
    assert len(pb.feeds) >= 3          # 즉답 필러 + 답변 문장들
    assert orch.state == State.IDLE


def test_bare_wake_word_greets_and_opens_follow_up():
    orch, pb = _make()
    orch.stt = _WakeSTT("자비스")

    async def run():
        orch._on_wake_utterance(np.zeros(8000, dtype=np.float32))
        await orch._task
        return asyncio.get_running_loop().time() < orch._follow_up_until

    in_window = asyncio.run(run())
    assert len(pb.feeds) == 1          # "Yes, sir?" 한 마디
    assert in_window
    assert orch.state == State.IDLE


def test_non_wake_utterance_discarded():
    orch, pb = _make()
    orch.stt = _WakeSTT("오늘 진짜 덥네 그치")

    async def run():
        orch._on_wake_utterance(np.zeros(16000, dtype=np.float32))
        await orch._task

    asyncio.run(run())
    assert pb.feeds == []
    assert orch.state == State.IDLE


def test_follow_up_accepts_command_without_wake_word():
    orch, pb = _make()
    orch.stt = _WakeSTT("내일 날씨는 어때?")

    async def run():
        orch._follow_up_until = asyncio.get_running_loop().time() + 5.0
        orch._on_wake_utterance(np.zeros(16000, dtype=np.float32))
        await orch._task

    asyncio.run(run())
    assert len(pb.feeds) >= 3


def test_pipeline_reopens_follow_up_window():
    orch, _ = _make()

    async def run():
        await orch._pipeline(np.zeros(16000, dtype=np.float32))
        return asyncio.get_running_loop().time() < orch._follow_up_until

    assert asyncio.run(run())


def test_wake_gate_blocks_outside_idle_and_cooldown():
    orch, _ = _make()

    async def run():
        loop = asyncio.get_running_loop()
        assert orch._wake_gate()                    # IDLE + 쿨다운 없음
        orch.state = State.SPEAKING
        assert not orch._wake_gate()                # 말하는 중엔 닫힘
        orch.state = State.IDLE
        orch._wake_blocked_until = loop.time() + 5.0
        assert not orch._wake_gate()                # 에코 쿨다운 동안 닫힘

    asyncio.run(run())


def test_wake_ignored_when_busy():
    orch, pb = _make()
    orch.stt = _WakeSTT("자비스 안녕")
    orch.state = State.THINKING

    async def run():
        orch._on_wake_utterance(np.zeros(16000, dtype=np.float32))
        assert orch._task is None                   # 태스크가 만들어지지 않아야 한다

    asyncio.run(run())
    assert pb.feeds == []
