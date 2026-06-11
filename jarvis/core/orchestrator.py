from __future__ import annotations

import asyncio
import contextlib

import numpy as np

from ..audio.util import resample
from ..audio.wake import match_wake
from ..hud.level import audio_level, chunk_levels
from .control_gate import CONTROL_GATE
from .events import State
from .interpret import detect_lang, interpret_speak_korean

_HUD_HOP_S = 0.1  # orb level update cadence (10 Hz)


def format_latency(stt_s: float | None, first_s: float) -> str:
    """튜닝용 한 줄 지연 로그 — 측정 없이는 반복(로드맵 4단계) 불가."""
    if stt_s is None:
        return f"[지연] 두뇌 첫문장 {first_s:.2f}s"
    return (f"[지연] STT {stt_s:.2f}s · 두뇌 첫문장 {first_s:.2f}s"
            f" · 합계 {stt_s + first_s:.2f}s")


class Orchestrator:
    """Wires Activator -> capture -> STT -> Brain -> SentenceChunker -> TTS -> VC ->
    playback. Barge-in cancels the in-flight Brain pipeline Task (CancelledError
    suppressed) and aborts playback. ``hud`` (optional OrbServer) receives best-effort
    {state, level} publishes so the on-screen orb reacts to the conversation."""

    def __init__(self, *, settings, activator, capture, stt, brain, chunker, tts, vc,
                 playback, hud=None, micstream=None, wake=None):
        self.settings = settings
        self.activator = activator
        self.capture = capture
        self.stt = stt
        self.brain = brain
        self.chunker = chunker
        self.tts = tts
        self.vc = vc
        self.playback = playback
        self.hud = hud
        self.micstream = micstream
        self.wake = wake
        self.proactive = None  # ProactiveEngine — 배선(__main__)에서 주입, run()이 시작
        self.interpret_mode = False  # "통역 모드" — 두뇌 우회, 한↔영 통역만
        self.state = State.IDLE
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task | None = None
        self._bg_tasks: set[asyncio.Task] = set()
        self._mic_meter: asyncio.Task | None = None
        # Instant acknowledgement spoken the moment you finish — then JARVIS thinks.
        self._ack_i = 0
        self._ack_cache: dict[str, np.ndarray] = {}
        # 연속대화: 답변 직후 이 시각까지는 웨이크워드 없이 follow-up을 받는다.
        self._follow_up_until = 0.0
        # 에코 쿨다운: 자비스 발화 직후 잔향을 자기 목소리로 오인하지 않도록.
        self._wake_blocked_until = 0.0
        self._last_stt_s: float | None = None
        # Speaking levels queue: _speak pushes per-hop levels; the pump publishes
        # them at playback cadence so the orb moves WITH the audio.
        self._spk_levels: asyncio.Queue[float] = asyncio.Queue()
        self._spk_pump: asyncio.Task | None = None
        self._attentive_timer: asyncio.Task | None = None
        self._warm_task: asyncio.Task | None = None
        self._remote_busy = False

    # ----- PTT callbacks (invoked from the pynput listener thread) -----
    def _press(self) -> None:
        if self._loop:
            self._loop.call_soon_threadsafe(self._on_press)

    def _release(self) -> None:
        if self._loop:
            self._loop.call_soon_threadsafe(self._on_release)

    def _on_press(self) -> None:
        # Barge-in: a press while a pipeline is running cancels it before re-capturing.
        if self._task is not None and not self._task.done():
            # Keep a strong ref: the loop only weakly references tasks, so a bare
            # create_task() can be GC'd mid-await and silently skip playback.abort().
            bg = asyncio.create_task(self._cancel_pipeline())
            self._bg_tasks.add(bg)
            bg.add_done_callback(self._bg_tasks.discard)
        self.state = State.CAPTURING
        self.capture.start()
        self._publish("listening")
        if self._mic_meter is None or self._mic_meter.done():
            self._mic_meter = asyncio.create_task(self._mic_meter_loop())

    def _on_release(self) -> None:
        if self._mic_meter is not None:
            self._mic_meter.cancel()
            self._mic_meter = None
        pcm = self.capture.stop()
        if self.wake is None and self.micstream is not None:
            # PTT 전용 모드: 누르는 동안만 마이크 점등(상시-온은 웨이크 모드 전용).
            self.micstream.stop()
        if self._remote_busy:
            self._to_idle()  # 원격 턴 진행 중 — PTT 발화 폐기(두뇌 동시 사용 방지)
            return
        self.state = State.TRANSCRIBING
        self._task = asyncio.create_task(self._pipeline(pcm))

    async def _mic_meter_loop(self) -> None:
        # Live input meter: the orb pulses with the USER's voice while the key is held.
        with contextlib.suppress(asyncio.CancelledError):
            while self.state == State.CAPTURING:
                tail = self.capture.level_tail()
                self._publish("listening", audio_level(tail))
                await asyncio.sleep(_HUD_HOP_S)

    def _publish(self, state: str, level: float = 0.0, text: str | None = None) -> None:
        # Best-effort: the orb HUD must never break the voice pipeline.
        if self.hud is not None:
            try:
                self.hud.publish(state, level, text)
            except Exception:
                pass

    def _to_idle(self) -> None:
        # 상태 복귀와 HUD publish는 반드시 한 쌍이다 — 따로 쓰다 한쪽을 빼먹으면
        # 오브가 PROCESSING에 갇힌다(실제로 났던 버그). IDLE 복귀는 전부 여기로.
        self.state = State.IDLE
        self._publish("idle")

    # ----- pipeline -----
    async def _cancel_pipeline(self) -> None:
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._drain_levels()  # stop the orb animating speech that was just cancelled
        if self._spk_pump is not None and not self._spk_pump.done():
            self._spk_pump.cancel()
        self.playback.abort()
        # State transitions are owned by _on_press/_on_release; do NOT set IDLE here —
        # during a barge-in this runs after _on_press already set CAPTURING.

    async def _pipeline(self, pcm: np.ndarray) -> None:
        try:
            lang = None if self.interpret_mode else self.settings.language
            t0 = asyncio.get_running_loop().time()
            text = await asyncio.to_thread(self.stt.transcribe, pcm, 16000, lang)
            self._last_stt_s = asyncio.get_running_loop().time() - t0
            await self._pipeline_text(text)
        except Exception as exc:  # noqa: BLE001 - 한 턴의 실패가 상태를 가두면 안 된다
            print(f"[파이프라인] 오류(IDLE 복귀): {exc}")
            self._to_idle()

    async def _pipeline_text(self, text: str, *, ack: bool = True) -> None:
        if not text.strip():
            self._to_idle()
            return
        ctl = self._control_command(text)
        if ctl is not None:
            await self._toggle_control(ctl)
            return
        cmd = self._interpret_command(text)
        if cmd is not None:
            await self._toggle_interpret(cmd)
            return
        if self.interpret_mode:
            await self._interpret_turn(text)
            return
        self.state = State.THINKING
        self._publish("thinking")
        t_think = asyncio.get_running_loop().time()
        first_done = False

        def _mark_first() -> None:
            nonlocal first_done
            if first_done:
                return
            first_done = True
            try:
                dt = asyncio.get_running_loop().time() - t_think
                print(format_latency(self._last_stt_s, dt))
            except Exception:  # noqa: BLE001 - 계측이 턴을 깨면 안 된다
                pass
            self._last_stt_s = None

        if ack:
            await self._play_ack()  # "One moment, sir." — 능동 알림은 생략(아무도 안 기다림)
        async for delta in self.brain.respond(text):
            for sentence in self.chunker.feed(delta):
                _mark_first()
                await self._speak(sentence)
        tail = self.chunker.flush()
        if tail:
            _mark_first()
            await self._speak(tail)
        # The Korean subtitle is only complete once the whole reply has streamed (the
        # '[KO]' part comes last). Publish it now and hold "speaking" until the queued
        # audio actually finishes playing — otherwise the orb/subtitle vanish mid-sentence.
        await self._finish_speaking(getattr(self.brain, "last_subtitle", "") or "")
        self.state = State.IDLE
        if self.wake is not None:
            self._enter_attentive()
        else:
            # PTT 전용 모드: follow-up을 들어줄 리스너가 없다 — '듣는 중' 표시와
            # 죽은 창을 열지 않는다.
            self._publish("idle")

    async def _finish_speaking(self, subtitle: str) -> None:
        if subtitle:
            self._publish("speaking", 0.3, subtitle)  # show the subtitle under SPEAKING
        # Wait out the audio: the speaking pump drains one queued level per hop (~the
        # audio's length), and the playback ring must empty too.
        for _ in range(int(30 / _HUD_HOP_S)):  # cap ~30s safety
            pump_busy = self._spk_pump is not None and not self._spk_pump.done()
            pending = self.playback.pending() if hasattr(self.playback, "pending") else 0
            if not pump_busy and pending <= 0:
                break
            await asyncio.sleep(_HUD_HOP_S)

    # ----- wake word (영화식 호출: 키 없이 "자비스") -----
    def _wake_gate(self) -> bool:
        # WakeListener는 IDLE이고 에코 쿨다운이 지난 동안만 들을 수 있다.
        try:
            now = asyncio.get_running_loop().time()
        except RuntimeError:
            return False
        return self.state == State.IDLE and now >= self._wake_blocked_until

    # 웨이크 판정엔 발화 앞부분만 변환한다 — 잡담 전체(최대 30초)를 위스퍼에
    # 태우는 게 상시 청취의 지배적 배터리 비용이라서다. 매칭이 확정된 뒤에만
    # 전체를 변환해 명령 전문을 얻는다.
    _WAKE_PREFIX_S = 4.0

    def _on_wake_utterance(self, pcm: np.ndarray) -> None:
        # WakeListener가 같은 루프에서 호출. self._task로 돌려 PTT 바지인이
        # 기존 경로 그대로 취소할 수 있게 한다.
        if not self._wake_gate():
            # 전달 시점에 전체 게이트(상태+에코 쿨다운)를 재판정한다 — 폴링 게이트만
            # 믿으면 게이트가 닫히기 직전 버퍼된 발화가 새어 들어온다.
            return
        if self._task is not None and not self._task.done():
            return
        arrived = asyncio.get_running_loop().time()
        self.state = State.TRANSCRIBING
        self._publish("thinking")  # 웨이크 변환 중에도 오브가 반응하도록
        self._task = asyncio.create_task(self._handle_wake(pcm, arrived))

    async def _handle_wake(self, pcm: np.ndarray, arrived: float | None = None) -> None:
        try:
            loop = asyncio.get_running_loop()
            t0 = loop.time()
            # follow-up 판정은 발화가 '도착한' 시각 기준 — STT가 걸린 시간만큼
            # 창이 잠식되어 끝자락 follow-up이 조용히 버려지는 일을 막는다.
            ref = arrived if arrived is not None else loop.time()
            in_follow_up = ref < self._follow_up_until
            prefix_n = int(self._WAKE_PREFIX_S * 16000)
            gate_pcm = pcm if in_follow_up or len(pcm) <= prefix_n else pcm[:prefix_n]
            text = await asyncio.to_thread(
                self.stt.transcribe, gate_pcm, 16000, self.settings.language)
            matched, command = match_wake(text, self.settings.wake_words)
            if not matched and in_follow_up:
                command = text.strip()  # follow-up 창: 웨이크워드 생략 가능
                matched = bool(command)
            if not matched:
                self._to_idle()  # 우리 부른 게 아니다 — 즉시 폐기(로그 금지)
                return
            if len(gate_pcm) < len(pcm):
                full_text = await asyncio.to_thread(
                    self.stt.transcribe, pcm, 16000, self.settings.language)
                m2, c2 = match_wake(full_text, self.settings.wake_words)
                if m2:
                    command = c2  # 전문에서 명령을 다시 뽑는다(접두 변환은 잘려 있다)
            if not command:
                await self._wake_greet()  # "자비스"만 불렀다
                return
            self._last_stt_s = loop.time() - t0
            await self._pipeline_text(command)
        except Exception as exc:  # noqa: BLE001 - 웨이크 경로는 스스로 회복해야 한다
            print(f"[웨이크] 처리 오류(IDLE 복귀): {exc}")
            self._to_idle()

    async def _wake_greet(self) -> None:
        await self._play_phrase("Yes, sir?", "네, 주인님?")
        await self._finish_speaking("")
        self.state = State.IDLE
        self._enter_attentive()  # 웨이크 경로에서만 도달 — 리스너 존재가 보장된다

    def _enter_attentive(self) -> None:
        # follow-up 창을 열고 HUD에 '아직 듣는 중'을 은은하게 표시한다.
        loop = asyncio.get_running_loop()
        self._follow_up_until = loop.time() + self.settings.follow_up_s
        self._wake_blocked_until = loop.time() + self.settings.wake_echo_cooldown_s
        self._publish("attentive")
        if self._attentive_timer is not None and not self._attentive_timer.done():
            self._attentive_timer.cancel()
        # 강한 참조는 이 속성이 보유한다(다음 창에서 교체) — _bg_tasks 중복 등재 불필요.
        self._attentive_timer = asyncio.create_task(self._attentive_expiry())

    async def _attentive_expiry(self) -> None:
        loop = asyncio.get_running_loop()
        await asyncio.sleep(max(0.0, self._follow_up_until - loop.time()))
        # 창이 연장(새 답변)되지 않았고 여전히 한가할 때만 STANDBY로 복귀.
        if self.state == State.IDLE and loop.time() >= self._follow_up_until:
            self._publish("idle")

    # ----- 통역 모드 -----
    _INTERP_ON = ("켜", "시작", "on")
    _INTERP_OFF = ("꺼", "끄", "종료", "off", "그만")

    def _interpret_command(self, text: str) -> str | None:
        if "통역" not in text:
            return None
        if any(w in text for w in self._INTERP_OFF):
            return "off"
        if any(w in text for w in self._INTERP_ON):
            return "on"
        return None

    async def _toggle_interpret(self, cmd: str) -> None:
        self.interpret_mode = (cmd == "on")
        if self.interpret_mode and hasattr(self.brain, "warm_interpret"):
            # 안내 발화가 나가는 동안 백그라운드 예열 — 첫 통역 턴 콜드스타트 제거.
            self._warm_task = asyncio.create_task(self._warm_interpret_safe())
        en, ko = (("Interpreter mode on, sir.", "통역 모드를 켰습니다.")
                  if self.interpret_mode
                  else ("Interpreter mode off, sir.", "통역 모드를 껐습니다."))
        await self._play_phrase(en, ko)
        await self._finish_speaking("")
        self.state = State.IDLE
        if self.wake is not None:
            self._enter_attentive()
        else:
            self._publish("idle")

    async def _warm_interpret_safe(self) -> None:
        try:
            await self.brain.warm_interpret()
        except Exception:  # noqa: BLE001 - 예열 실패는 무해
            pass

    async def _interpret_turn(self, text: str) -> None:
        try:
            src = detect_lang(text)
            if src == "ko":
                out = await self.brain.translate(text, "English")
                await self._speak(out)
                await self._finish_speaking("")
            else:
                out = await self.brain.translate(text, "Korean")
                self.state = State.SPEAKING
                self._publish("speaking", 0.4, out)  # 한국어 통역도 오브·자막 반응
                await asyncio.to_thread(
                    interpret_speak_korean, out, self.settings.interpret_ko_voice)
        except Exception as exc:  # noqa: BLE001 - 통역 한 줄 실패가 모드를 깨면 안 된다
            print(f"[통역] 오류: {exc}")
        self.state = State.IDLE
        if self.wake is not None:
            self._enter_attentive()
        else:
            self._publish("idle")

    # ----- 화면 제어 모드 (3c) -----
    def _control_command(self, text: str) -> str | None:
        if "화면 제어" not in text and "화면제어" not in text:
            return None
        if any(w in text for w in self._INTERP_OFF):
            return "off"
        if "켜져" in text or "켜졌" in text:
            return None  # 상태 질문("켜져 있어?") — 토글 아님, 두뇌로
        if "켜" in text:
            return "on"
        return None

    async def _toggle_control(self, cmd: str) -> None:
        # interpret과 달리 턴을 가로채는 모드가 아니다 — 게이트 플래그만 연다.
        # 두뇌는 평소 경로에서 capture_screen/screen_control을 쓴다.
        if cmd == "on":
            CONTROL_GATE.enable(self.settings.screen_control_ttl_s)
            en, ko = ("Screen control engaged, sir. It will switch itself off "
                      "in a few minutes.",
                      "화면 제어 모드를 켰습니다. 잠시 후 자동으로 꺼집니다.")
        else:
            CONTROL_GATE.disable()
            en, ko = ("Screen control disengaged, sir.", "화면 제어 모드를 껐습니다.")
        await self._play_phrase(en, ko)
        await self._finish_speaking("")
        self.state = State.IDLE
        if self.wake is not None:
            self._enter_attentive()
        else:
            self._publish("idle")

    # ----- 능동 알림 (ProactiveEngine이 호출) -----
    def _can_announce(self) -> bool:
        return (self.state == State.IDLE
                and (self._task is None or self._task.done()))

    async def announce(self, prompt: str) -> None:
        # 같은 루프에서 불린다. self._task로 돌려 PTT/웨이크가 평소처럼 끼어들 수 있게.
        self._last_stt_s = None
        if not self._can_announce():
            return
        self.state = State.THINKING
        self._publish("thinking")  # 상태와 HUD는 한 쌍 — 게이트 선점과 동시에 표시
        self._task = asyncio.create_task(self._handle_announce(prompt))

    async def _handle_announce(self, prompt: str) -> None:
        try:
            await self._pipeline_text(f"[SYSTEM EVENT] {prompt}", ack=False)
        except Exception as exc:  # noqa: BLE001 - 알림 실패가 상태를 가두면 안 된다
            print(f"[능동] 처리 오류(IDLE 복귀): {exc}")
            self._to_idle()

    # ----- 아이폰 원격 명령 -----
    async def remote_turn(self, text: str) -> dict:
        """원격(HTTP) 텍스트 턴 — TTS 없이 텍스트로만 답한다(사용자 부재).
        THINKING 상태가 웨이크 게이트를 막고 _remote_busy가 PTT 경로를 막아
        두뇌 동시 사용(응답 훔치기 레이스)을 차단한다."""
        if not text.strip():
            return {"reply": "무엇을 도와드릴까요?"}
        if self._remote_busy or not self._can_announce():
            return {"reply": "지금 다른 일을 처리하고 있습니다. 잠시 후 다시 시도해 주세요."}
        self._remote_busy = True
        self.state = State.THINKING
        self._publish("thinking")
        if hasattr(self.brain, "remote_mode"):
            self.brain.remote_mode = True
        try:
            parts: list[str] = []
            async for delta in self.brain.respond(text):
                parts.append(delta)
            en = "".join(parts).strip()
            ko = (getattr(self.brain, "last_subtitle", "") or "").strip()
            return {"reply": ko or en or "답을 만들지 못했습니다.", "reply_en": en}
        except Exception as exc:  # noqa: BLE001 - 원격 한 턴 실패가 상태를 가두면 안 된다
            print(f"[원격] 처리 오류: {exc}")
            return {"reply": "처리 중 오류가 났습니다."}
        finally:
            if hasattr(self.brain, "remote_mode"):
                self.brain.remote_mode = False
            self._remote_busy = False
            self._to_idle()

    # Instant acknowledgements (English speech, Korean subtitle). Cached after first
    # synth so they play with zero delay — JARVIS answers the moment you stop talking.
    ACK_FILLERS = (
        ("One moment, sir.", "잠시만요."),
        ("Just a moment, sir.", "잠시만 기다려 주십시오."),
        ("Right away, sir.", "바로 처리하겠습니다."),
        ("Let me see, sir.", "확인해 보겠습니다."),
    )

    async def _play_ack(self) -> None:
        en, ko = self.ACK_FILLERS[self._ack_i % len(self.ACK_FILLERS)]
        self._ack_i += 1
        await self._play_phrase(en, ko)

    async def _synth_phrase(self, en: str) -> np.ndarray | None:
        out = self._ack_cache.get(en)
        if out is None:
            try:
                audio = await self.tts.synth(en)
                conv = await asyncio.to_thread(self.vc.convert, audio, self.tts.sample_rate)
                out = resample(np.asarray(conv, dtype=np.float32).reshape(-1),
                               self.vc.sample_rate, self.settings.playback_rate)
            except Exception:  # noqa: BLE001 - canned phrase is best-effort
                return None
            self._ack_cache[en] = out
        return out

    async def _play_phrase(self, en: str, ko: str) -> None:
        out = await self._synth_phrase(en)
        if out is None:
            return
        self._queue_audio(out, ko)

    async def warm_phrases(self) -> None:
        # 부팅 직후 호출 — 캔드 프레이즈를 미리 합성해 첫 ACK·인사도 0지연.
        for en, _ko in (*self.ACK_FILLERS, ("Yes, sir?", "네, 주인님?")):
            await self._synth_phrase(en)

    def _queue_audio(self, out: np.ndarray, subtitle: str | None = None) -> None:
        # 발화 송출의 단일 꼬리: 상태 전환 → HUD(자막 포함) → 레벨 펌프 → 재생.
        # 캔드 프레이즈(_play_phrase)와 문장(_speak)이 같은 경로를 타야 펌프/HUD
        # 수정이 한쪽만 적용되는 사고가 없다.
        self.state = State.SPEAKING
        self._publish("speaking", audio_level(out), subtitle)
        for lv in chunk_levels(out, self.settings.playback_rate, _HUD_HOP_S):
            self._spk_levels.put_nowait(lv)
        if self._spk_pump is None or self._spk_pump.done():
            self._spk_pump = asyncio.create_task(self._spk_pump_loop())
        self.playback.feed(out)

    async def _speak(self, sentence: str, subtitle: str | None = None) -> None:
        # Empty/whitespace chunks make MeloTTS emit empty audio, which crashes RVC
        # (zero-size reduction) and killed the whole turn with no sound — skip them.
        if not sentence.strip():
            return
        self.state = State.SPEAKING
        try:
            audio = await self.tts.synth(sentence)                # at tts.sample_rate
        except Exception:  # noqa: BLE001 - one bad sentence must not kill the answer
            return
        arr = np.asarray(audio, dtype=np.float32).reshape(-1)
        if arr.size == 0 or float(np.max(np.abs(arr))) < 1e-4:  # empty/silent crashes RVC
            return
        audio = arr
        try:
            converted = await asyncio.to_thread(self.vc.convert, audio, self.tts.sample_rate)
            out = resample(converted, self.vc.sample_rate, self.settings.playback_rate)
        except Exception:  # noqa: BLE001 - RVC failed: speak base voice, never go silent
            out = resample(np.asarray(audio, dtype=np.float32).reshape(-1),
                           self.tts.sample_rate, self.settings.playback_rate)
        self._queue_audio(out, subtitle or None)

    async def _spk_pump_loop(self) -> None:
        with contextlib.suppress(asyncio.CancelledError):
            while True:
                try:
                    lv = self._spk_levels.get_nowait()
                except asyncio.QueueEmpty:
                    break
                self._publish("speaking", lv)
                await asyncio.sleep(_HUD_HOP_S)

    def _drain_levels(self) -> None:
        while not self._spk_levels.empty():
            with contextlib.suppress(asyncio.QueueEmpty):
                self._spk_levels.get_nowait()

    # ----- run loop -----
    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        self.playback.start()
        if self.micstream is not None and self.wake is not None:
            # 웨이크 모드에서만 상시-온. PTT 전용이면 누를 때만 연다(프라이버시).
            # 열기 실패는 부팅을 막지 않는다 — _want_running이 켜진 채라 웨이크
            # 루프의 ensure_running()이 2초 간격으로 자가 복구를 시도한다.
            try:
                self.micstream.start()
            except Exception as exc:  # noqa: BLE001
                print(f"[마이크] 입력 스트림 시작 실패(자동 재시도): {exc}")
        if self.wake is not None:
            self.wake.start(self._on_wake_utterance, self._wake_gate)
        if self.proactive is not None:
            self.proactive.start()
        self.activator.start(self._press, self._release)
        await asyncio.Event().wait()  # run until process is killed
