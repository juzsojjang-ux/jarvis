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
    orch.wake = object()                 # follow-up 창은 웨이크 리스너가 있을 때만 연다

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


def test_wake_stt_error_recovers_to_idle():
    class _BoomSTT:
        def transcribe(self, pcm, sample_rate=16000, language="ko"):
            raise RuntimeError("stt boom")

    orch, pb = _make()
    orch.stt = _BoomSTT()

    async def run():
        orch._on_wake_utterance(np.zeros(16000, dtype=np.float32))
        await orch._task

    asyncio.run(run())
    assert pb.feeds == []
    assert orch.state == State.IDLE          # 죽지 않고 IDLE로 복귀해야 웨이크가 살아있다


def test_brain_error_recovers_to_idle():
    class _BoomBrain:
        async def respond(self, user_text):
            raise RuntimeError("brain boom")
            yield  # pragma: no cover - 제너레이터로 만들기 위한 형식

    orch, _ = _make()
    orch.brain = _BoomBrain()
    orch.stt = _WakeSTT("자비스 안녕")

    async def run():
        orch._on_wake_utterance(np.zeros(16000, dtype=np.float32))
        await orch._task

    asyncio.run(run())
    assert orch.state == State.IDLE


class _FakeHud:
    def __init__(self):
        self.events = []

    def publish(self, state, level=0.0, text=None):
        self.events.append(state)


def test_non_wake_discard_publishes_idle_to_hud():
    # 잡담 폐기 후 publish를 빼먹으면 오브가 PROCESSING에 갇힌다(실제 발견 버그).
    orch, pb = _make()
    orch.hud = _FakeHud()
    orch.stt = _WakeSTT("그냥 잡담이었어요")

    async def run():
        orch._on_wake_utterance(np.zeros(16000, dtype=np.float32))
        await orch._task

    asyncio.run(run())
    assert pb.feeds == []
    assert orch.hud.events[-1] == "idle"


def test_ptt_only_answer_does_not_enter_attentive():
    # 웨이크 리스너가 없으면 '듣는 중' 표시도, 죽은 follow-up 창도 열지 않는다.
    orch, _ = _make()                    # wake=None (PTT 전용)
    orch.hud = _FakeHud()

    async def run():
        await orch._pipeline(np.zeros(16000, dtype=np.float32))

    asyncio.run(run())
    assert orch._follow_up_until == 0.0
    assert "attentive" not in orch.hud.events
    assert orch.hud.events[-1] == "idle"


def test_wake_cooldown_blocks_delivery():
    # 폴링 게이트가 닫히기 직전 버퍼된 발화도 전달 시점 재판정에서 막혀야 한다.
    orch, pb = _make()
    orch.stt = _WakeSTT("자비스 안녕")

    async def run():
        orch._wake_blocked_until = asyncio.get_running_loop().time() + 5.0
        orch._on_wake_utterance(np.zeros(16000, dtype=np.float32))
        assert orch._task is None

    asyncio.run(run())
    assert pb.feeds == []


def test_announce_speaks_without_ack_filler():
    # 사용자가 기다리는 게 아니므로 "잠시만요" 필러 없이 바로 본문만.
    orch, pb = _make()
    orch.wake = object()                  # follow-up 창 조건

    async def run():
        await orch.announce("배터리가 18%까지 떨어졌다")
        await orch._task
        return asyncio.get_running_loop().time() < orch._follow_up_until

    in_window = asyncio.run(run())
    assert len(pb.feeds) >= 1                 # 본문은 나간다
    # 같은 가짜 두뇌로 ack 포함 경로(_pipeline)와 비교해 필러 한 개가 빠졌는지 확인
    orch2, pb2 = _make()
    orch2.wake = object()

    async def run2():
        await orch2._pipeline(np.zeros(16000, dtype=np.float32))

    asyncio.run(run2())
    assert len(pb2.feeds) == len(pb.feeds) + 1  # ack 필러 정확히 1개 차이
    assert orch.state == State.IDLE
    assert in_window                      # 알림 후에도 되묻기 창이 열린다


def test_announce_skipped_when_busy():
    orch, pb = _make()
    orch.state = State.SPEAKING

    async def run():
        await orch.announce("아무거나")
        assert orch._task is None

    asyncio.run(run())
    assert pb.feeds == []


def test_announce_error_recovers_to_idle():
    class _BoomBrain2:
        async def respond(self, user_text):
            raise RuntimeError("brain boom")
            yield  # pragma: no cover

    orch, _ = _make()
    orch.brain = _BoomBrain2()

    async def run():
        await orch.announce("이벤트")
        await orch._task

    asyncio.run(run())
    assert orch.state == State.IDLE


def test_can_announce_reflects_state():
    orch, _ = _make()
    assert orch._can_announce()
    orch.state = State.THINKING
    assert not orch._can_announce()


class _XlateBrain:
    async def respond(self, user_text):
        raise AssertionError("respond called in interpret mode")
        yield

    async def translate(self, text, target):
        return f"<{target}:{text}>"


def _interp(orch):
    orch.brain = _XlateBrain()
    orch.interpret_mode = True


def test_interpret_command_toggles_on_off():
    orch, pb = _make()

    async def run():
        await orch._pipeline_text("통역 모드 켜줘")
        on = orch.interpret_mode
        await orch._pipeline_text("통역 모드 꺼줘")
        return on, orch.interpret_mode

    on, off = asyncio.run(run())
    assert on is True and off is False
    assert len(pb.feeds) >= 1


def test_interpret_korean_input_speaks_english():
    orch, pb = _make()
    _interp(orch)

    async def run():
        await orch._pipeline_text("안녕하세요")
    asyncio.run(run())
    assert len(pb.feeds) >= 1
    assert orch.state == State.IDLE


def test_interpret_english_input_speaks_korean(monkeypatch):
    orch, pb = _make()
    _interp(orch)
    spoken_ko = []

    def fake_say(text, voice="Yuna", runner=None):
        spoken_ko.append((text, voice))

    monkeypatch.setattr("jarvis.core.orchestrator.interpret_speak_korean", fake_say)

    async def run():
        await orch._pipeline_text("hello there")
    asyncio.run(run())
    assert spoken_ko and "hello there" in spoken_ko[0][0]
    assert pb.feeds == []


def test_interpret_translate_failure_recovers():
    orch, pb = _make()

    class _BoomXlate:
        async def respond(self, user_text):
            raise AssertionError
            yield

        async def translate(self, text, target):
            raise RuntimeError("api down")

    orch.brain = _BoomXlate()
    orch.interpret_mode = True

    async def run():
        await orch._pipeline_text("안녕")
    asyncio.run(run())
    assert orch.state == State.IDLE
    assert orch.interpret_mode is True


def test_control_command_toggles_gate_on_off(monkeypatch):
    from jarvis.core import orchestrator as orch_mod
    orch, pb = _make()
    calls = []

    class _FakeGate:
        def enable(self, ttl):
            calls.append(("enable", ttl))

        def disable(self):
            calls.append(("disable",))

    monkeypatch.setattr(orch_mod, "CONTROL_GATE", _FakeGate())

    async def run():
        await orch._pipeline_text("화면 제어 모드 켜줘")
        await orch._pipeline_text("화면 제어 모드 꺼줘")

    asyncio.run(run())
    assert calls == [("enable", orch.settings.screen_control_ttl_s), ("disable",)]
    assert len(pb.feeds) >= 1  # 안내 발화
    assert orch.state == State.IDLE


def test_control_command_matching():
    orch, _ = _make()
    assert orch._control_command("화면 제어 모드 켜줘") == "on"
    assert orch._control_command("화면제어 켜") == "on"
    assert orch._control_command("화면 제어 모드 꺼줘") == "off"
    assert orch._control_command("화면 제어 그만") == "off"
    assert orch._control_command("통역 모드 켜줘") is None
    assert orch._control_command("화면에 뭐 있어") is None
    assert orch._control_command("화면 제어 모드 켜져 있어?") is None
    assert orch._control_command("화면 제어 시작") is None
    assert orch._control_command("screen control on") is None


def test_interpret_toggle_on_warms_translate():
    orch, _pb = _make()
    warmed = []

    class _WarmBrain(_XlateBrain):
        async def warm_interpret(self):
            warmed.append(True)

    orch.brain = _WarmBrain()

    async def run():
        await orch._pipeline_text("통역 모드 켜줘")
        if orch._warm_task is not None:
            await orch._warm_task
    asyncio.run(run())
    assert warmed == [True]


def test_control_toggle_does_not_hijack_normal_turns(monkeypatch):
    """control 모드는 interpret과 달리 턴을 가로채지 않는다 — 토글 후 일반
    질문은 평소처럼 두뇌로 간다."""
    from jarvis.core import orchestrator as orch_mod

    class _FakeGate:
        def enable(self, ttl):
            pass

        def disable(self):
            pass

    monkeypatch.setattr(orch_mod, "CONTROL_GATE", _FakeGate())
    orch, pb = _make()

    async def run():
        await orch._pipeline_text("화면 제어 모드 켜줘")
        await orch._pipeline_text("안녕")  # 일반 두뇌 경로

    asyncio.run(run())
    assert orch.state == State.IDLE
    assert len(pb.feeds) >= 2  # 토글 안내 + 두뇌 답변 둘 다 발화됨


def test_control_command_checked_before_interpret(monkeypatch):
    """'화면 제어'가 들어간 토글은 interpret_mode 중에도 control 토글로 잡힌다."""
    from jarvis.core import orchestrator as orch_mod
    calls = []

    class _FakeGate:
        def enable(self, ttl):
            calls.append("enable")

        def disable(self):
            calls.append("disable")

    monkeypatch.setattr(orch_mod, "CONTROL_GATE", _FakeGate())
    orch, pb = _make()
    _interp(orch)  # 통역 모드 중

    async def run():
        await orch._pipeline_text("화면 제어 모드 켜줘")

    asyncio.run(run())
    assert calls == ["enable"]
    assert orch.interpret_mode is True  # 통역 모드는 건드리지 않는다


def test_format_latency_with_and_without_stt():
    from jarvis.core.orchestrator import format_latency
    assert format_latency(0.42, 1.31) == "[지연] STT 0.42s · 두뇌 첫문장 1.31s · 합계 1.73s"
    assert format_latency(None, 1.31) == "[지연] 두뇌 첫문장 1.31s"


def test_pipeline_text_prints_latency_line(capsys):
    orch, _pb = _make()

    async def run():
        await orch._pipeline_text("안녕")
    asyncio.run(run())
    assert "[지연]" in capsys.readouterr().out


def test_warm_phrases_precaches_ack_and_greet():
    orch, _pb = _make()

    async def run():
        await orch.warm_phrases()
    asyncio.run(run())
    cached = set(orch._ack_cache)
    assert {en for en, _ in orch.ACK_FILLERS} <= cached
    assert "Yes, sir?" in cached


def test_remote_turn_collects_text_without_tts():
    orch, pb = _make()

    async def run():
        return await orch.remote_turn("안녕")
    res = asyncio.run(run())
    assert res["reply"]
    assert pb.feeds == []  # 원격 턴은 절대 말하지 않는다
    assert orch.state == State.IDLE


def test_remote_turn_busy_when_not_idle():
    orch, _pb = _make()
    orch.state = State.THINKING

    async def run():
        return await orch.remote_turn("안녕")
    res = asyncio.run(run())
    assert "다른 일" in res["reply"]


def test_remote_turn_sets_and_clears_remote_mode():
    orch, _pb = _make()
    seen = []

    class _FlagBrain:
        remote_mode = False
        last_subtitle = "한국어 답"

        async def respond(self, text):
            seen.append(self.remote_mode)
            yield "english answer"

    orch.brain = _FlagBrain()

    async def run():
        return await orch.remote_turn("hi")
    res = asyncio.run(run())
    assert seen == [True]                 # 응답 생성 중엔 원격 모드
    assert orch.brain.remote_mode is False  # 끝나면 해제
    assert res["reply"] == "한국어 답"
    assert res["reply_en"] == "english answer"


def test_remote_turn_recovers_on_brain_error():
    orch, _pb = _make()

    class _BoomBrain:
        async def respond(self, text):
            raise RuntimeError("down")
            yield

    orch.brain = _BoomBrain()

    async def run():
        return await orch.remote_turn("hi")
    res = asyncio.run(run())
    assert "오류" in res["reply"]
    assert orch.state == State.IDLE


def test_remote_turn_blocks_concurrent_remote():
    orch, _pb = _make()
    orch._remote_busy = True
    orch.state = State.IDLE

    async def run():
        return await orch.remote_turn("hi")
    res = asyncio.run(run())
    assert "다른 일" in res["reply"]


def test_remote_busy_closes_voice_gates():
    orch, _pb = _make()
    orch._remote_busy = True
    orch.state = State.IDLE
    assert orch._can_announce() is False
    if hasattr(orch, "_wake_gate"):
        async def run():
            return orch._wake_gate()
        assert asyncio.run(run()) is False


def test_on_press_ignored_while_remote_busy():
    orch, _pb = _make()
    orch._remote_busy = True
    orch.state = State.IDLE
    orch._on_press()
    assert orch.state == State.IDLE  # CAPTURING으로 안 바뀜
