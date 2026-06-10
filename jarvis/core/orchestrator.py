from __future__ import annotations

import asyncio
import contextlib

import numpy as np

from ..audio.util import resample
from ..hud.level import audio_level, chunk_levels
from .events import State

_HUD_HOP_S = 0.1  # orb level update cadence (10 Hz)


class Orchestrator:
    """Wires Activator -> capture -> STT -> Brain -> SentenceChunker -> TTS -> VC ->
    playback. Barge-in cancels the in-flight Brain pipeline Task (CancelledError
    suppressed) and aborts playback. ``hud`` (optional OrbServer) receives best-effort
    {state, level} publishes so the on-screen orb reacts to the conversation."""

    def __init__(self, *, settings, activator, capture, stt, brain, chunker, tts, vc,
                 playback, hud=None):
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
        self.state = State.IDLE
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task | None = None
        self._bg_tasks: set[asyncio.Task] = set()
        self._mic_meter: asyncio.Task | None = None
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

    def _publish(self, state: str, level: float = 0.0) -> None:
        # Best-effort: the orb HUD must never break the voice pipeline.
        if self.hud is not None:
            try:
                self.hud.publish(state, level)
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
        if not text.strip():
            self.state = State.IDLE
            self._publish("idle")
            return
        self.state = State.THINKING
        self._publish("thinking")
        async for delta in self.brain.respond(text):
            for sentence in self.chunker.feed(delta):
                await self._speak(sentence)
        tail = self.chunker.flush()
        if tail:
            await self._speak(tail)
        self.state = State.IDLE
        self._publish("idle")

    async def _speak(self, sentence: str) -> None:
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
        self.activator.start(self._press, self._release)
        await asyncio.Event().wait()  # run until process is killed
