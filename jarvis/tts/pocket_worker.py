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
# Pocket TTS warns "Chunk has N tokens (max 50)" and may skip words when a chunk
# exceeds its 50-token budget. The tokenizer is English-centric: a Hangul syllable
# costs ~3 tokens (measured: a 16-syllable Korean confirm prompt → 55 tokens), an
# English word ~1.3. So the cap must be TOKEN-weighted, not word-counted — a
# 10-word Korean sentence already blows a word cap that 24 English words fit under.
_TOKEN_BUDGET = 42.0  # safety margin under pocket's max 50


def _token_cost(word: str) -> float:
    cost = 0.3  # space/join overhead
    for ch in word:
        if "가" <= ch <= "힣":
            cost += 3.0      # Hangul syllable ≈ 3 tokens
        elif ch.isascii() and ch.isalnum():
            cost += 0.35     # English ≈ 1.3 tokens per ~4-letter word
        else:
            cost += 0.8      # punctuation/quotes/other
    return cost


def split_for_pocket(text: str, budget: float = _TOKEN_BUDGET) -> list[str]:
    """Split text into pieces under Pocket's per-chunk token budget — preferring
    clause breaks (comma/period), hard-cutting comma-less run-ons at the budget."""
    text = text.strip()
    if not text:
        return []
    out: list[str] = []
    buf: list[str] = []
    cost = 0.0
    for w in text.split():
        wc = _token_cost(w)
        if buf and cost + wc > budget:
            out.append(" ".join(buf))
            buf, cost = [], 0.0
        buf.append(w)
        cost += wc
        # 예산의 60%를 넘었고 절 경계면 미리 끊는다(다음 절이 통째로 들어가게)
        if cost >= budget * 0.6 and w.endswith((",", ";", ":", ".", "!", "?")):
            out.append(" ".join(buf))
            buf, cost = [], 0.0
    if buf:
        out.append(" ".join(buf))
    # 초단편 조각(토큰 ~6 미만)은 이웃과 병합 — Pocket이 아주 짧은 입력에서
    # "어 어앴비"처럼 웅얼거리는(뭉개지는) 발화를 만드는 것을 막는다.
    merged: list[str] = []
    for p in out:
        cost = sum(_token_cost(w) for w in p.split())
        if merged and cost < 6.0:
            merged[-1] = merged[-1] + " " + p
        else:
            merged.append(p)
    return merged


def _trim_edge_silence(a: np.ndarray, sr: int, thresh: float = 0.012,
                       keep_ms: int = 35) -> np.ndarray:
    """조각의 앞뒤 무음/늘어지는 꼬리를 다듬는다 — Pocket이 조각 끝에 붙이는 긴 무음이
    '중간에 늘어지는' 체감을 만든다. keep_ms 만큼만 남겨 자연스러운 호흡은 유지."""
    if a.size == 0:
        return a
    nz = np.where(np.abs(a) > thresh)[0]
    if nz.size == 0:
        return a[: int(keep_ms * sr / 1000)]
    keep = int(keep_ms * sr / 1000)
    return a[max(0, nz[0] - keep): min(a.size, nz[-1] + keep)]


def make_pocket_synth():
    """Build the Pocket-TTS synth: english text -> (float32 pcm, 24000), JARVIS voice."""
    from pocket_tts import TTSModel

    ref = os.environ.get(
        "JARVIS_POCKET_REF", os.path.expanduser("~/jarvis/voice_models/jarvis_ref.wav"))
    # temp 0.45: 사용자 청취 비교로 확정 — 기본 0.7보다 레퍼런스(진짜 자비스)에 더 충실해
    # 음색 유사도가 높다(JARVIS_POCKET_TEMP로 재정의 가능). 낮을수록 충실/차분.
    temp = float(os.environ.get("JARVIS_POCKET_TEMP", "0.45"))
    model = TTSModel.load_model(temp=temp)
    voice_state = model.get_state_for_audio_prompt(ref)  # clone once at startup
    gap = np.zeros(int(0.025 * SAMPLE_RATE), dtype=np.float32)  # 25ms — 늘어짐/끊김 줄임

    fade_n = int(0.005 * SAMPLE_RATE)  # 조각 경계 5ms 페이드 — 클릭/뭉개짐 방지
    fade_in = np.linspace(0.0, 1.0, fade_n, dtype=np.float32)
    fade_out = fade_in[::-1].copy()

    def synth(text: str):
        pieces = [p for p in split_for_pocket(text)
                  if any(ch.isalnum() or "가" <= ch <= "힣" for ch in p)]  # 부호만 스킵
        if not pieces:
            return np.zeros(0, dtype=np.float32), SAMPLE_RATE
        parts: list[np.ndarray] = []
        for i, piece in enumerate(pieces):
            # frames_after_eos=1: 문장 끝 뒤에 생성하는 여분 프레임 최소화(늘어지는 꼬리↓)
            audio = model.generate_audio(voice_state, piece, frames_after_eos=1)
            a = audio.numpy() if hasattr(audio, "numpy") else np.asarray(audio)
            a = np.asarray(a, dtype=np.float32).reshape(-1)
            a = _trim_edge_silence(a, int(model.sample_rate))  # 앞뒤 무음 꼬리 다듬기
            if a.size > 2 * fade_n:  # 경계 페이드(첫/끝 5ms)
                a[:fade_n] *= fade_in
                a[-fade_n:] *= fade_out
            parts.append(a)
            if i < len(pieces) - 1:
                parts.append(gap)
        pcm = np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)
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
