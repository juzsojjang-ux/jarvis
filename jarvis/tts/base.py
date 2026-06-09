from typing import Protocol

import numpy as np


class TTSBackend(Protocol):
    sample_rate: int

    def warm(self) -> None: ...
    async def synth(self, text: str) -> np.ndarray: ...  # mono float32 at self.sample_rate
