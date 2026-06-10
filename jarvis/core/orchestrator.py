from __future__ import annotations

import asyncio
import contextlib

import numpy as np

from ..audio.util import resample
from ..audio.wake import match_wake
from ..hud.level import audio_level, chunk_levels
from .events import State

_HUD_HOP_S = 0.1  # orb level update cadence (10 Hz)


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
        # Speaking levels queue: _speak pushes per-hop levels; the pump publishes
        # them at playback cadence so the orb moves WITH the audio.
        self._spk_levels: asyncio.Queue[float] = asyncio.Queue()
        self._spk_pump: asyncio.Task | None = None

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
        text = await asyncio.to_thread(self.stt.transcribe, pcm, 16000, self.settings.language)
        await self._pipeline_text(text)

    async def _pipeline_text(self, text: str) -> None:
        if not text.strip():
            self.state = State.IDLE
            self._publish("idle")
            return
        self.state = State.THINKING
        self._publish("thinking")
        await self._play_ack()  # "One moment, sir." the instant you finish — then think
        async for delta in self.brain.respond(text):
            for sentence in self.chunker.feed(delta):
                await self._speak(sentence)
        tail = self.chunker.flush()
        if tail:
            await self._speak(tail)
        # The Korean subtitle is only complete once the whole reply has streamed (the
        # '[KO]' part comes last). Publish it now and hold "speaking" until the queued
        # audio actually finishes playing — otherwise the orb/subtitle vanish mid-sentence.
        await self._finish_speaking(getattr(self.brain, "last_subtitle", "") or "")
        self.state = State.IDLE
        self._enter_attentive()

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

    def _on_wake_utterance(self, pcm: np.ndarray) -> None:
        # WakeListener가 같은 루프에서 호출. self._task로 돌려 PTT 바지인이
        # 기존 경로 그대로 취소할 수 있게 한다.
        if self.state != State.IDLE:
            return
        if self._task is not None and not self._task.done():
            return
        self.state = State.TRANSCRIBING
        self._task = asyncio.create_task(self._handle_wake(pcm))

    async def _handle_wake(self, pcm: np.ndarray) -> None:
        text = await asyncio.to_thread(
            self.stt.transcribe, pcm, 16000, self.settings.language)
        matched, command = match_wake(text, self.settings.wake_words)
        if not matched and asyncio.get_running_loop().time() < self._follow_up_until:
            command = text.strip()  # follow-up 창: 웨이크워드 생략 가능
            matched = bool(command)
        if not matched:
            self.state = State.IDLE  # 우리 부른 게 아니다 — 즉시 폐기(로그 금지)
            return
        if not command:
            await self._wake_greet()  # "자비스"만 불렀다
            return
        await self._pipeline_text(command)

    async def _wake_greet(self) -> None:
        await self._play_phrase("Yes, sir?", "네, 주인님?")
        await self._finish_speaking("")
        self.state = State.IDLE
        self._enter_attentive()

    def _enter_attentive(self) -> None:
        # follow-up 창을 열고 HUD에 '아직 듣는 중'을 은은하게 표시한다.
        loop = asyncio.get_running_loop()
        self._follow_up_until = loop.time() + self.settings.follow_up_s
        self._wake_blocked_until = loop.time() + 0.5  # 발화 잔향 쿨다운
        self._publish("attentive")
        timer = asyncio.create_task(self._attentive_expiry())
        self._bg_tasks.add(timer)
        timer.add_done_callback(self._bg_tasks.discard)

    async def _attentive_expiry(self) -> None:
        loop = asyncio.get_running_loop()
        await asyncio.sleep(max(0.0, self._follow_up_until - loop.time()))
        # 창이 연장(새 답변)되지 않았고 여전히 한가할 때만 STANDBY로 복귀.
        if self.state == State.IDLE and loop.time() >= self._follow_up_until:
            self._publish("idle")

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

    async def _play_phrase(self, en: str, ko: str) -> None:
        out = self._ack_cache.get(en)
        if out is None:
            try:
                audio = await self.tts.synth(en)
                conv = await asyncio.to_thread(self.vc.convert, audio, self.tts.sample_rate)
                out = resample(np.asarray(conv, dtype=np.float32).reshape(-1),
                               self.vc.sample_rate, self.settings.playback_rate)
            except Exception:  # noqa: BLE001 - canned phrase is best-effort
                return
            self._ack_cache[en] = out
        self.state = State.SPEAKING
        self._publish("speaking", audio_level(out), ko)
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
        # Queue per-hop levels; the pump publishes them at playback cadence so the orb
        # moves WITH the voice (not one static value per sentence).
        # Subtitle (Korean) shows under SPEAKING; first speaking publish carries the text.
        self._publish("speaking", audio_level(out), subtitle or None)
        for lv in chunk_levels(out, self.settings.playback_rate, _HUD_HOP_S):
            self._spk_levels.put_nowait(lv)
        if self._spk_pump is None or self._spk_pump.done():
            self._spk_pump = asyncio.create_task(self._spk_pump_loop())
        self.playback.feed(out)

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
        if self.micstream is not None:
            self.micstream.start()
        if self.wake is not None:
            self.wake.start(self._on_wake_utterance, self._wake_gate)
        self.activator.start(self._press, self._release)
        await asyncio.Event().wait()  # run until process is killed
