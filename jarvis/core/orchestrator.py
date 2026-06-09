from __future__ import annotations

import asyncio
import contextlib

import numpy as np

from ..audio.util import resample
from ..hud.level import audio_level
from .events import State


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

    def _on_release(self) -> None:
        pcm = self.capture.stop()
        self.state = State.TRANSCRIBING
        self._task = asyncio.create_task(self._pipeline(pcm))

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
        self.state = State.SPEAKING
        audio = await self.tts.synth(sentence)                    # at tts.sample_rate
        converted = await asyncio.to_thread(self.vc.convert, audio, self.tts.sample_rate)
        out = resample(converted, self.vc.sample_rate, self.settings.playback_rate)
        self._publish("speaking", audio_level(out))
        self.playback.feed(out)

    # ----- run loop -----
    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        self.playback.start()
        self.activator.start(self._press, self._release)
        await asyncio.Event().wait()  # run until process is killed
