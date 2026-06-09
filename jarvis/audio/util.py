import numpy as np
import soxr


def resample(pcm: np.ndarray, src: int, dst: int) -> np.ndarray:
    """Resample mono float32 PCM from src to dst Hz using soxr (HQ)."""
    pcm = np.asarray(pcm, dtype=np.float32)
    if src == dst:
        return pcm
    return np.asarray(
        soxr.resample(pcm, float(src), float(dst), quality="HQ"), dtype=np.float32
    )
