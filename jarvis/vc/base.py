from typing import Protocol

import numpy as np


class VoiceConversion(Protocol):
    sample_rate: int

    def warm(self) -> None: ...
    def convert(self, pcm: np.ndarray, in_rate: int) -> np.ndarray: ...
