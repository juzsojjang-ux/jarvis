from typing import Protocol

import numpy as np


class STTBackend(Protocol):
    def warm(self) -> None: ...
    def transcribe(
        self, pcm: np.ndarray, sample_rate: int = 16000, language: str = "ko"
    ) -> str: ...
