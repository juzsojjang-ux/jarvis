r"""Framed IPC between the main venv and the MeloTTS worker (.venv-tts).

Per message: one JSON header line ('\n'-terminated) + optional raw payload.
  Request : {"type":"synth","text":"..."}                         (no payload)
  Response: {"type":"pcm","sample_rate":44100,"nbytes":N}\n<N bytes float32 LE>
          | {"type":"error","message":"..."}                      (no payload)
PCM is mono float32 little-endian in [-1, 1] at sample_rate.
"""
from __future__ import annotations

import json

import numpy as np


def pack_request(text: str) -> bytes:
    return json.dumps({"type": "synth", "text": text}, ensure_ascii=False).encode("utf-8") + b"\n"


def read_request(stream):
    line = stream.readline()
    if not line:
        return None
    msg = json.loads(line.decode("utf-8"))
    if msg.get("type") != "synth":
        raise ValueError(f"unexpected request: {msg!r}")
    return msg["text"]


def pack_response(pcm, sample_rate: int) -> bytes:
    buf = np.asarray(pcm, dtype="<f4").tobytes()
    header = json.dumps({"type": "pcm", "sample_rate": int(sample_rate),
                         "nbytes": len(buf)}).encode("utf-8") + b"\n"
    return header + buf


def pack_error(message: str) -> bytes:
    return json.dumps({"type": "error", "message": message}).encode("utf-8") + b"\n"


def _read_exact(stream, n: int) -> bytes:
    chunks, got = [], 0
    while got < n:
        c = stream.read(n - got)
        if not c:
            raise EOFError("short read from tts worker")
        chunks.append(c)
        got += len(c)
    return b"".join(chunks)


def read_response(stream):
    line = stream.readline()
    if not line:
        raise EOFError("tts worker closed the stream")
    msg = json.loads(line.decode("utf-8"))
    if msg.get("type") == "error":
        raise RuntimeError(f"tts worker error: {msg.get('message')}")
    if msg.get("type") != "pcm":
        raise ValueError(f"unexpected response: {msg!r}")
    raw = _read_exact(stream, int(msg["nbytes"]))
    return np.frombuffer(raw, dtype="<f4").astype(np.float32), int(msg["sample_rate"])
