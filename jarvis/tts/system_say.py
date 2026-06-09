import asyncio
import os
import subprocess
import tempfile
import wave

import numpy as np


class SystemSayTTS:
    """M1 placeholder voice: macOS `say` rendered to a LEI16 WAV, loaded to mono
    float32. We force `--data-format=LEI16@<rate>` + `--file-format=WAVE` so the
    output is plain little-endian PCM readable by the stdlib `wave` module (macOS
    `say`'s default AIFF uses a compression type Python's aifc can't decode)."""

    def __init__(self, voice: str = "Yuna", sample_rate: int = 22050):
        self._voice = voice
        self.sample_rate = sample_rate

    def warm(self) -> None:
        # `say` is always available on macOS; nothing to preload.
        return None

    async def synth(self, text: str) -> np.ndarray:
        return await asyncio.to_thread(self._synth, text)

    def _synth(self, text: str) -> np.ndarray:
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "say.wav")
            subprocess.run(
                [
                    "say", "-v", self._voice,
                    f"--data-format=LEI16@{self.sample_rate}",
                    "--file-format=WAVE",
                    "-o", out, text,
                ],
                check=True,
            )
            with wave.open(out, "rb") as f:
                self.sample_rate = f.getframerate()
                channels = f.getnchannels()
                raw = f.readframes(f.getnframes())
        pcm = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
        if channels > 1:
            pcm = pcm.reshape(-1, channels).mean(axis=1)
        return np.ascontiguousarray(pcm, dtype=np.float32)
