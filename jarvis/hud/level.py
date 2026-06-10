from __future__ import annotations

import numpy as np


def chunk_levels(pcm, rate: int, hop_s: float = 0.1, gain: float = 4.0) -> list[float]:
    """Per-hop RMS levels of mono PCM — drives the orb in sync with playback."""
    x = np.asarray(pcm, dtype=np.float32).reshape(-1)
    hop = max(1, int(hop_s * rate))
    return [audio_level(x[i:i + hop], gain) for i in range(0, len(x), hop)]


def audio_level(pcm, gain: float = 4.0) -> float:
    """RMS amplitude of mono float32 PCM mapped to ~0..1 for the orb's reactivity.

    Empty/silent -> 0.0. `gain` lifts speech RMS (typically 0.05–0.25) into a lively
    visual range; the result is clamped to [0, 1].
    """
    x = np.asarray(pcm, dtype=np.float32).reshape(-1)
    if x.size == 0:
        return 0.0
    rms = float(np.sqrt(np.mean(x * x)))
    return max(0.0, min(1.0, rms * gain))
