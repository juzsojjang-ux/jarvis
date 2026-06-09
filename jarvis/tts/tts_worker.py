"""Persistent MeloTTS-KR worker. Runs INSIDE .venv-tts ONLY (never called by
the main venv -- make_melo_synth() imports melo lazily). Reads synth requests
on stdin, writes float32 PCM on stdout via jarvis.tts.ipc. MeloTTS -> 44100 Hz.

Run:  ~/jarvis/.venv-tts/bin/python -m jarvis.tts.tts_worker
"""
from __future__ import annotations

import sys

import numpy as np

from jarvis.tts import ipc

SAMPLE_RATE = 44100


def make_melo_synth():
    """Build the real MeloTTS-KR synth: text -> (float32 pcm, 44100)."""
    import os
    import tempfile

    import soundfile as sf
    from melo.api import TTS
    model = TTS(language="KR", device="cpu")
    spk = model.hps.data.spk2id["KR"]

    def synth(text: str):
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            model.tts_to_file(text, spk, path, speed=1.0)
            pcm, sr = sf.read(path, dtype="float32")
            if pcm.ndim > 1:
                pcm = pcm.mean(axis=1).astype(np.float32)
            return pcm.astype(np.float32), sr
        finally:
            os.unlink(path)
    return synth


def run_once(synth, in_stream, out_stream) -> bool:
    text = ipc.read_request(in_stream)
    if text is None:
        return False
    try:
        pcm, sr = synth(text)
        out_stream.write(ipc.pack_response(pcm, sr))
    except Exception as exc:  # report, keep serving
        out_stream.write(ipc.pack_error(repr(exc)))
    out_stream.flush()
    return True


def serve(synth, in_stream, out_stream) -> None:
    while run_once(synth, in_stream, out_stream):
        pass


def main() -> None:
    serve(make_melo_synth(), sys.stdin.buffer, sys.stdout.buffer)


if __name__ == "__main__":
    main()
