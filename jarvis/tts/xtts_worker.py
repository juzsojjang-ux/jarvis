"""Persistent XTTS-v2 worker. Runs INSIDE .venv-xtts ONLY (never the main venv --
coqui-tts/torch are isolated there). Clones the JARVIS timbre zero-shot from a short
reference (env JARVIS_XTTS_REF) and synthesizes Korean over jarvis.tts.ipc. 24000 Hz.

Conditioning latents are computed ONCE at startup, so each request is inference-only.
Tuned to avoid XTTS's run-on/rambling failure (sentence splitting + repetition penalty)
and the output tail is trimmed of trailing silence. Two-venv isolation: reachable only
via PYTHONPATH=<repo root> set by the spawning backend.

Run:  ~/jarvis/.venv-xtts/bin/python -m jarvis.tts.xtts_worker
"""
from __future__ import annotations

import os
import sys

import numpy as np

from jarvis.tts.tts_worker import serve  # generic ipc serve loop

SAMPLE_RATE = 24000


def _trim_tail(pcm: np.ndarray, sr: int, thr: float = 0.012, keep: float = 0.12) -> np.ndarray:
    nz = np.where(np.abs(pcm) > thr)[0]
    if nz.size == 0:
        return pcm
    end = min(len(pcm), int(nz[-1]) + int(keep * sr))
    return pcm[:end]


def make_xtts_synth():
    """Build the XTTS-KR synth: text -> (float32 pcm, 24000), JARVIS timbre."""
    os.environ.setdefault("COQUI_TOS_AGREED", "1")
    from TTS.api import TTS

    ref = os.environ.get(
        "JARVIS_XTTS_REF", os.path.expanduser("~/jarvis/voice_models/jarvis_ref.wav"))
    device = os.environ.get("JARVIS_XTTS_DEVICE", "cpu")
    lang = os.environ.get("JARVIS_XTTS_LANG", "ko")
    # Tuned to avoid run-on/rambling and keep timbre stable on a low-bitrate reference.
    temperature = float(os.environ.get("JARVIS_XTTS_TEMP", "0.6"))
    repetition_penalty = float(os.environ.get("JARVIS_XTTS_REP", "5.0"))

    api = TTS("tts_models/multilingual/multi-dataset/xtts_v2")
    try:
        api.to(device)
    except Exception:  # noqa: BLE001 - MPS/optional; CPU is the safe default
        pass
    model = api.synthesizer.tts_model
    # Longer conditioning window = richer timbre capture from the cleaned reference.
    gpt_cond, speaker = model.get_conditioning_latents(
        audio_path=[ref], gpt_cond_len=12, max_ref_length=30)

    def synth(text: str):
        out = model.inference(
            text, lang, gpt_cond, speaker,
            temperature=temperature, repetition_penalty=repetition_penalty,
            top_k=50, top_p=0.85, length_penalty=1.0, enable_text_splitting=True)
        wav = np.asarray(out["wav"], dtype=np.float32).reshape(-1)
        wav = _trim_tail(wav, SAMPLE_RATE)
        # Light post: DC removal + peak normalize for consistent, fuller loudness.
        if wav.size:
            wav = wav - float(np.mean(wav))
            peak = float(np.max(np.abs(wav)))
            if peak > 1e-5:
                wav = wav * (0.95 / peak)
        return wav.astype(np.float32), SAMPLE_RATE

    return synth


def main() -> None:
    # coqui-tts/torch/tqdm print to stdout; protect the binary IPC channel by dup'ing
    # the real stdout for IPC and pointing fd 1 at stderr (same trick as tts_worker).
    ipc_out = os.fdopen(os.dup(sys.stdout.fileno()), "wb")
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    serve(make_xtts_synth(), sys.stdin.buffer, ipc_out)


if __name__ == "__main__":
    main()
