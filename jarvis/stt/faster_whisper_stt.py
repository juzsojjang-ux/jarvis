"""크로스플랫폼 STT — faster-whisper(CTranslate2). 윈도우 CPU/CUDA + 맥 모두 동작.
같은 Whisper 모델이라 mlx-whisper와 인식 품질 동일(런타임만 다름). MLXWhisperSTT의
_UNSET 센티넬·자동감지(None 보존) 계약을 그대로 따른다(통역 모드 필수)."""
from __future__ import annotations
import numpy as np

_UNSET = object()  # 미지정과 '의도적 None(자동감지)' 구분


class FasterWhisperSTT:
    def __init__(self, repo: str, language: str = "ko", compute_type: str = "int8",
                 device: str = "cpu", model_factory=None):
        self._repo = repo
        self._language = language
        self._compute = compute_type
        self._device = device
        self._model_factory = model_factory  # 주입(테스트) — None이면 실제 로드
        self._model = None

    def _ensure(self):
        if self._model is None:
            if self._model_factory is not None:
                self._model = self._model_factory(self._repo, self._device, self._compute)
            else:
                from faster_whisper import WhisperModel
                self._model = WhisperModel(self._repo, device=self._device,
                                           compute_type=self._compute)
        return self._model

    def warm(self) -> None:
        try:
            self.transcribe(np.zeros(16000, dtype=np.float32))
        except Exception:  # noqa: BLE001 - 예열 실패는 무해
            pass

    def transcribe(self, pcm: np.ndarray, sample_rate: int = 16000,
                   language=_UNSET) -> str:
        lang = self._language if language is _UNSET else language  # None 보존(자동감지)
        audio = np.asarray(pcm, dtype=np.float32).reshape(-1)
        try:
            model = self._ensure()
            segments, _info = model.transcribe(audio, language=lang)
            return "".join(getattr(s, "text", "") for s in segments).strip()
        except Exception:  # noqa: BLE001 - 전사 실패는 빈 문자열(상위가 IDLE 처리)
            return ""
