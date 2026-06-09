# Absolute import resolves to the installed top-level package, not this same-named module.
import mlx_whisper
import numpy as np


class MLXWhisperSTT:
    def __init__(self, repo: str, language: str = "ko"):
        self._repo = repo
        self._language = language

    def warm(self) -> None:
        # First call caches/loads weights; transcribe 1s of silence.
        self.transcribe(np.zeros(16000, dtype=np.float32))

    def transcribe(self, pcm: np.ndarray, sample_rate: int = 16000, language: str = "ko") -> str:
        audio = np.asarray(pcm, dtype=np.float32)
        result = mlx_whisper.transcribe(
            audio, path_or_hf_repo=self._repo, language=language or self._language
        )
        return result["text"].strip()
