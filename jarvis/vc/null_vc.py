import numpy as np


class NullVC:
    """M1 identity passthrough. Output rate equals input rate; sample_rate tracks it
    so the orchestrator can resample to the playback rate."""

    def __init__(self, sample_rate: int = 48000):
        self.sample_rate = sample_rate

    def warm(self) -> None:
        return None

    def convert(self, pcm: np.ndarray, in_rate: int) -> np.ndarray:
        self.sample_rate = in_rate
        return np.asarray(pcm, dtype=np.float32)
