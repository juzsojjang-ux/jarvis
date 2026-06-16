import asyncio
import sys

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


def test_fast_reply_skips_ack_filler():
    # 개선된 동작: 빠른 답에는 "잠시만 기다려주세요" 필러를 내보내지 않는다.
    orch, pb = _make()
    asyncio.run(orch._pipeline(np.zeros(16000, dtype=np.float32)))
    assert orch._ack_cache == {}          # 필러 합성·재생 자체를 안 함
    assert len(pb.feeds) >= 1             # 답변은 정상 출력
    assert orch.state == State.IDLE


def test_slow_reply_plays_ack_filler():
    # 두뇌가 늦으면(도구·긴 생각) 그제서야 필러를 내보낸다.
    orch, pb = _make()
    orch._ack_delay_s = 0.02

    class _SlowBrain:
        async def respond(self, user_text):
            await asyncio.sleep(0.15)
            for d in ["안녕하", "세요. 무엇을 ", "도와드릴까요?"]:
                yield d

    orch.brain = _SlowBrain()
    asyncio.run(orch._pipeline(np.zeros(16000, dtype=np.float32)))
    assert orch._ack_cache != {}          # 필러가 합성·재생됨
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
    assert len(pb.feeds) >= 1          # 답변이 음성으로 나간다(빠른 답이면 필러 생략)
    assert orch.state == State.IDLE


def test_bare_wake_listens_then_greets_on_silence():
    # 새 동작: "자비스"만 부르면 바로 막지 말고 wake_grace_s초 듣는다. 그 안에 말을
    # 시작하면 명령으로 받고, 정적이면 그제야 "네 주인님?"으로 인사한다.
    orch, pb = _make()
    orch.stt = _WakeSTT("자비스")
    orch.settings.wake_grace_s = 0.05  # 테스트용 짧은 창

    async def run():
        orch._on_wake_utterance(np.zeros(8000, dtype=np.float32))
        await orch._task
        no_greet_yet = len(pb.feeds) == 0  # 즉시 막지 않음(피드 없음)
        in_window = asyncio.get_running_loop().time() < orch._follow_up_until
        greet_armed = orch._greet_if_idle  # 정적이면 인사하도록 무장
        await orch._attentive_timer        # 0.05s 정적 경과 → 인사
        return no_greet_yet, in_window, greet_armed

    no_greet_yet, in_window, greet_armed = asyncio.run(run())
    assert no_greet_yet
    assert in_window
    assert greet_armed
    assert len(pb.feeds) == 1          # 정적 후에야 "Yes, sir?" 한 마디
    assert orch.state == State.IDLE


def test_speech_start_uses_start_not_end_of_utterance():
    # 1.0s(16000샘플) 발화가 t=10.0에 도착(종료) → 시작은 t≈9.0
    assert abs(Orchestrator._speech_start(10.0, 16000) - 9.0) < 1e-6
    assert Orchestrator._speech_start(5.0, 0) == 5.0  # 빈 발화: 시작=도착


def test_long_command_started_in_window_is_accepted():
    # 창이 '말 끝'으로는 이미 닫혔지만 '말 시작'은 창 안 → 시작 시점 기준이라 수용.
    orch, pb = _make()
    orch.wake = object()
    orch.stt = _WakeSTT("내일 오후 일정 전부 정리해서 알려줘")  # 웨이크워드 없음

    async def run():
        now = asyncio.get_running_loop().time()
        orch._follow_up_until = now - 0.5          # 발화 끝(now)은 창 밖
        pcm = np.zeros(32000, dtype=np.float32)    # 2.0s → 시작 now-2.0 (창 안)
        await orch._handle_wake(pcm, arrived=now)
        return len(pb.feeds)

    assert asyncio.run(run()) >= 1                  # 시작이 창 안이라 명령으로 수용


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
    assert len(pb.feeds) >= 1


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
    if sys.platform == "darwin":  # 오류 음성 안내가 say 경로라 재생 피드 없음
        assert pb.feeds == []     # (다른 OS는 영어 자비스 음성으로 안내 → 피드 생김)
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
    assert orch._ack_cache == {}              # 능동 알림은 "잠시만요" 필러 없음
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


def test_trust_command_matching():
    orch, _ = _make()
    assert orch._trust_command("전권 모드 켜줘") == "on"
    assert orch._trust_command("전권 위임 켜") == "on"
    assert orch._trust_command("전권 모드 꺼줘") == "off"
    assert orch._trust_command("전권 켜져 있어?") is None
    assert orch._trust_command("통역 모드 켜줘") is None
    assert orch._trust_command("화면 제어 모드 켜줘") is None


def test_toggle_trust_enables_gate(monkeypatch):
    from jarvis.core import orchestrator as om
    calls = []
    class _G:
        def enable(self, ttl): calls.append(("enable", ttl))
        def disable(self): calls.append(("disable",))
    monkeypatch.setattr(om, "TRUST_GATE", _G())
    orch, pb = _make()

    async def run():
        await orch._pipeline_text("전권 모드 켜줘")
        await orch._pipeline_text("전권 모드 꺼줘")
    asyncio.run(run())
    assert calls == [("enable", orch.settings.trust_mode_ttl_s), ("disable",)]
    assert len(pb.feeds) >= 1
    assert orch.state == State.IDLE


# ----- 자막 바로바로 + 사용량 + 한도 초과 알림 -----
class _CapHud:
    def __init__(self):
        self.texts = []

    def publish(self, state, level=0.0, text=None):
        if text:
            self.texts.append(text)


def test_subtitle_published_per_sentence_live():
    # 문장이 말해질 때마다 자막이 올라와야 한다(끝에 한 번이 아니라).
    orch, _pb = _make()
    orch.hud = _CapHud()
    asyncio.run(orch._pipeline_text("안녕", ack=False))
    assert len(orch.hud.texts) >= 2


def test_usage_command_shows_usage_subtitle():
    orch, _pb = _make()
    orch.hud = _CapHud()
    orch.usage.session = {"input": 111, "output": 22, "turns": 3}
    asyncio.run(orch._pipeline_text("사용량 알려줘", ack=False))
    assert any("111" in t for t in orch.hud.texts)


def test_limit_error_announces_on_screen(monkeypatch):
    import jarvis.core.orchestrator as om
    monkeypatch.setattr(om, "interpret_speak_korean", lambda *a, **k: None)
    orch, _pb = _make()
    orch.hud = _CapHud()

    class _LimitBrain:
        last_error = None

        async def respond(self, user_text):
            if False:
                yield ""
            raise RuntimeError("429 Too Many Requests: rate_limit exceeded")

    orch.brain = _LimitBrain()
    asyncio.run(orch._pipeline_text("안녕", ack=False))
    assert any("한도 초과" in t for t in orch.hud.texts)


def test_usage_command_matcher():
    orch, _pb = _make()
    assert orch._usage_command("사용량") is True
    assert orch._usage_command("토큰 얼마나 썼어") is True
    assert orch._usage_command("오늘 날씨 어때") is False


# ----- 알림 패널 + 오류 음성화 -----
class _NoticeHud:
    def __init__(self):
        self.texts = []
        self.notices = []

    def publish(self, state, level=0.0, text=None, notice=None):
        if text:
            self.texts.append(text)

    def publish_notice(self, notice):
        self.notices.append(notice)


def test_panel_command_matcher():
    orch, _pb = _make()
    assert orch._panel_command("패널 꺼") == "off"
    assert orch._panel_command("알림 닫아줘") == "off"
    assert orch._panel_command("패널 켜") == "on"
    assert orch._panel_command("오늘 날씨") is None


def test_panel_off_clears_notice_immediately():
    orch, _pb = _make()
    orch.hud = _NoticeHud()
    asyncio.run(orch._pipeline_text("패널 꺼", ack=False))
    assert "" in orch.hud.notices
    assert orch._panel_muted is True


def test_brain_error_announced_and_notified(monkeypatch):
    import jarvis.core.orchestrator as om
    monkeypatch.setattr(om, "interpret_speak_korean", lambda *a, **k: None)
    orch, _pb = _make()
    orch.hud = _NoticeHud()

    class _BadBrain:
        async def respond(self, user_text):
            if False:
                yield ""
            raise RuntimeError("boom")

    orch.brain = _BadBrain()
    asyncio.run(orch._pipeline_text("안녕", ack=False))
    assert orch.last_bug == "boom"
    assert any("오류" in n for n in orch.hud.notices)


def test_panel_muted_suppresses_notices():
    orch, _pb = _make()
    orch.hud = _NoticeHud()
    orch._panel_muted = True
    orch._notify("⚠ 오류 무언가")
    assert orch.hud.notices == []  # 음소거 중엔 새 알림 억제


# ----- 자막 한국어 보장(번역 누락 폴백) -----
def test_korean_subtitle_prefers_ko_marker():
    orch, _pb = _make()

    class _B:
        last_subtitle = "안녕하세요, 주인님."

        async def translate(self, t, lang):
            return "SHOULD_NOT"

    orch.brain = _B()
    out = asyncio.run(orch._korean_subtitle(["Hello, sir."]))
    assert out == "안녕하세요, 주인님."


def test_korean_subtitle_translates_when_ko_missing():
    orch, _pb = _make()

    class _B:
        last_subtitle = ""

        async def translate(self, t, lang):
            return "번역됨: " + t

    orch.brain = _B()
    out = asyncio.run(orch._korean_subtitle(["Good evening, sir."]))
    assert out.startswith("번역됨: Good evening")


def test_korean_subtitle_keeps_korean_spoken_no_translate():
    orch, _pb = _make()

    class _B:
        last_subtitle = ""

        async def translate(self, t, lang):
            raise AssertionError("한국어인데 번역하면 안 됨")

    orch.brain = _B()
    out = asyncio.run(orch._korean_subtitle(["안녕하세요 주인님"]))
    assert out == "안녕하세요 주인님"


def test_korean_subtitle_falls_back_to_spoken_on_translate_error():
    orch, _pb = _make()

    class _B:
        last_subtitle = ""

        async def translate(self, t, lang):
            raise RuntimeError("translate down")

    orch.brain = _B()
    out = asyncio.run(orch._korean_subtitle(["Hello sir"]))
    assert out == "Hello sir"  # 번역 실패해도 자막은 채운다


# ----- 전면 점검 배치: 화면제어/패널/자막동기/STT -----
def test_control_command_space_insensitive():
    orch, _pb = _make()
    assert orch._control_command("화면 제어 모드 켜줘") == "on"
    assert orch._control_command("화면제어모드 켜 줘") == "on"
    assert orch._control_command("제어 모드 켜줘") == "on"
    assert orch._control_command("화면 제어 모드 꺼줘") == "off"
    assert orch._control_command("화면 제어 켜져 있어?") is None
    assert orch._control_command("오늘 날씨") is None


def test_panel_content_request_goes_to_brain():
    # "패널에 X 보여줘"를 로컬 토글이 가로채면 안 된다(두뇌의 show_panel로 가야).
    orch, _pb = _make()
    assert orch._panel_command("패널에 오늘 일정 보여줘") is None
    assert orch._panel_command("패널에 날씨 띄워줘") is None
    assert orch._panel_command("패널 켜줘") == "on"     # 순수 토글만 로컬
    assert orch._panel_command("패널 꺼") == "off"
    assert orch._panel_command("알림 패널 닫아줘") == "off"


def test_tool_show_unmutes_panel():
    # "패널 꺼" 후에도 사용자가 두뇌에게 보여달라고 하면 떠야 한다.
    orch, _pb = _make()
    orch.hud = _NoticeHud()
    orch._panel_muted = True
    orch._panel_sink("오늘 일정 3건")
    assert orch._panel_muted is False
    assert orch.hud.notices[-1] == "오늘 일정 3건"


def test_tool_hide_does_not_unmute():
    orch, _pb = _make()
    orch.hud = _NoticeHud()
    orch._panel_muted = True
    orch._panel_sink("")
    assert orch._panel_muted is True
    assert orch.hud.notices[-1] == ""


# ----- 자막 타이밍: 말하는 동안 함께 흘러가고, 말 끝과 같이 끝나는지 -----
def test_subtitle_chunks_pace_with_audio():
    import time as _time

    class _TimedPlayback(_FakePlayback):
        """실시간으로 오디오가 소모되는 가짜 재생기 — pending이 시간에 따라 준다."""
        def __init__(self, seconds, rate=48000):
            super().__init__()
            self.rate = rate
            self.t0 = _time.monotonic()
            self.total = int(seconds * rate)

        def pending(self):
            consumed = int((_time.monotonic() - self.t0) * self.rate)
            return max(0, self.total - consumed)

    pb = _TimedPlayback(seconds=2.4)
    orch, _ = _make(playback=pb)
    shown = []  # (시각, 자막)

    class _TimingHud:
        def publish(self, state, level=0.0, text=None):
            if text:
                shown.append((_time.monotonic() - pb.t0, text))

    orch.hud = _TimingHud()
    # 3청크짜리 자막(각 ≤26자) — 오디오 2.4초에 맞춰 배분되어야 한다
    subtitle = "첫 번째 자막 조각입니다. 두 번째 자막 조각입니다. 세 번째 자막 조각입니다."
    asyncio.run(orch._finish_speaking(subtitle))
    texts = [t for _, t in shown]
    assert len(texts) >= 3                       # 모든 청크가 표시됨
    assert texts[0].startswith("첫 번째")          # 즉시 첫 청크
    assert shown[0][0] < 0.3                     # 시작과 동시에
    # 청크들이 오디오 구간(0~2.4s+여유) 안에서 순차 표시 — 한 번에 다 안 띄움
    gaps = [shown[i+1][0] - shown[i][0] for i in range(len(shown)-1)]
    assert all(g >= 0.7 for g in gaps), f"간격이 너무 촘촘함: {gaps}"
    assert shown[-1][0] <= 2.4 + 1.2, f"마지막 청크가 너무 늦음: {shown[-1][0]:.1f}s"


def test_remote_turn_includes_remote_context_marker():
    # 원격 턴은 두뇌에 '원격(부재중·발송 불가)' 컨텍스트를 알린다 — 모르면
    # "보낼까요?"처럼 응답 불가능한 되묻기를 한다(라이브 검증에서 발견).
    orch, _pb = _make()
    seen = {}

    class _RecBrain:
        last_subtitle = "원격 응답입니다."
        remote_mode = False

        async def respond(self, user_text):
            seen["text"] = user_text
            yield "Remote reply."

    orch.brain = _RecBrain()
    out = asyncio.run(orch.remote_turn("엄마한테 메시지 보내줘"))
    assert "[원격" in seen["text"] and "엄마한테 메시지 보내줘" in seen["text"]
    assert out["reply"] == "원격 응답입니다."
    assert orch.state == State.IDLE


def test_selfcheck_command_matches():
    from jarvis.core.orchestrator import Orchestrator
    m = Orchestrator._selfcheck_command
    class T:  # self 대용 — 매처는 self를 안 쓴다
        pass
    assert m(T(), "자가 진단 해줘")
    assert m(T(), "상태 점검 해봐")
    assert m(T(), "셀프 체크")
    assert not m(T(), "오늘 날씨 어때")
    assert not m(T(), "상태가 어떤 것 같아?")


def test_watch_command_matches():
    from jarvis.core.orchestrator import Orchestrator
    m = Orchestrator._watch_command
    class T:
        pass
    assert m(T(), "화면 봐줘") is True
    assert m(T(), "화면 지켜봐") is True
    assert m(T(), "화면 그만 봐") is False
    assert m(T(), "화면 감시 꺼") is False
    assert m(T(), "화면 캡처해줘") is None     # 일반 캡처 요청은 두뇌로
    assert m(T(), "오늘 날씨 어때") is None


def test_expand_command_matches():
    from jarvis.core.orchestrator import Orchestrator
    m = Orchestrator._expand_command
    class T: pass
    assert m(T(), "크게 띄워") is True
    assert m(T(), "패널 크게") is True
    assert m(T(), "확대해줘") is True
    assert m(T(), "작게 해") is False
    assert m(T(), "축소") is False
    assert m(T(), "오늘 날씨 어때") is None


# ---- 두뇌 예열(warm)을 첫 턴이 1회 대기 -----------------------------------
def test_await_warm_no_task_returns_immediately():
    o, _ = _make()
    o._warm_task = None
    asyncio.run(o._await_warm())  # 예외 없이 즉시 반환


def test_await_warm_waits_for_pending_then_passes():
    o, _ = _make()

    async def scenario():
        flag = {"done": False}

        async def warm():
            await asyncio.sleep(0.02)
            flag["done"] = True

        o._warm_task = asyncio.create_task(warm())
        await o._await_warm()
        assert flag["done"] is True   # 미완료 예열을 대기했다
        await o._await_warm()         # 두 번째 호출은 즉시 통과(끝남)

    asyncio.run(scenario())


def test_await_warm_swallows_exception():
    o, _ = _make()

    async def scenario():
        async def boom():
            raise RuntimeError("warm failed")

        o._warm_task = asyncio.create_task(boom())
        await asyncio.sleep(0.01)
        await o._await_warm()         # 예열 실패를 삼킨다(raise 안 함)

    asyncio.run(scenario())
