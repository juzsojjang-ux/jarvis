"""Hermetic stand-in for the MeloTTS worker: 0.1s 440Hz sine for any text,
using the real ipc framing. No MeloTTS / no .venv-tts required."""
import sys

import numpy as np

from jarvis.tts import tts_worker


def _sine(text):
    sr = 44100
    t = np.arange(int(0.1 * sr)) / sr
    return (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32), sr


if __name__ == "__main__":
    tts_worker.serve(_sine, sys.stdin.buffer, sys.stdout.buffer)
