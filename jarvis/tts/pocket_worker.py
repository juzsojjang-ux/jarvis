"""Persistent Pocket-TTS worker. Runs INSIDE .venv-pocket ONLY (Kyutai pocket-tts +
its torch live there). Clones the JARVIS voice ONCE from a reference (JARVIS_POCKET_REF)
and synthesizes ENGLISH text over jarvis.tts.ipc. 24000 Hz.

Pocket TTS is the engine from the NetHyTech "real JARVIS voice" video: a 100M Kyutai
model, CPU real-time, instant voice cloning. English-only — JARVIS replies in English
(the user may still speak Korean; STT handles that). Two-venv isolation: reachable only
via PYTHONPATH=<repo root> set by the spawning backend.

Run:  ~/jarvis/.venv-pocket/bin/python -m jarvis.tts.pocket_worker
"""
from __future__ import annotations

import os
import sys

import numpy as np

from jarvis.tts.tts_worker import serve  # generic ipc serve loop

SAMPLE_RATE = 24000


def make_pocket_synth():
    """Build the Pocket-TTS synth: english text -> (float32 pcm, 24000), JARVIS voice."""
    from pocket_tts import TTSModel

    ref = os.environ.get(
        "JARVIS_POCKET_REF", os.path.expanduser("~/jarvis/voice_models/jarvis_ref.wav"))
    model = TTSModel.load_model()
    voice_state = model.get_state_for_audio_prompt(ref)  # clone once at startup

    def synth(text: str):
        audio = model.generate_audio(voice_state, text)
        pcm = audio.numpy() if hasattr(audio, "numpy") else np.asarray(audio)
        pcm = np.asarray(pcm, dtype=np.float32).reshape(-1)
        if pcm.size:
            peak = float(np.max(np.abs(pcm)))
            if peak > 1e-5:
                pcm = pcm * (0.95 / peak)
        return pcm, int(model.sample_rate)

    return synth


def main() -> None:
    # pocket-tts / torch print to stdout; protect the binary IPC channel by dup'ing the
    # real stdout for IPC and pointing fd 1 at stderr (same trick as tts_worker).
    ipc_out = os.fdopen(os.dup(sys.stdout.fileno()), "wb")
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    serve(make_pocket_synth(), sys.stdin.buffer, ipc_out)


if __name__ == "__main__":
    main()
