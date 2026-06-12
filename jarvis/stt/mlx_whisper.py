# Absolute import resolves to the installed top-level package, not this same-named module.
import mlx_whisper
import numpy as np

_UNSET = object()  # 미지정과 '의도적 None(자동감지)'를 구분하기 위한 센티넬


class MLXWhisperSTT:
    def __init__(self, repo: str, language: str = "ko", initial_prompt: str | None = None):
        self._repo = repo
        self._language = language
        # 도메인 용어 바이어스 — Whisper는 initial_prompt에 등장한 어휘를 우선해
        # 받아적는다. "자비스/화면 제어 모드/전권 위임" 같은 명령어 인식률이 오른다.
        self._initial_prompt = initial_prompt

    def warm(self) -> None:
        # First call caches/loads weights; transcribe 1s of silence.
        self.transcribe(np.zeros(16000, dtype=np.float32))

    def transcribe(self, pcm: np.ndarray, sample_rate: int = 16000,
                   language=_UNSET) -> str:
        # language=None은 통역 모드의 자동 언어감지(절대 self._language로 뭉개지
        # 않는다). 인자를 안 주면(_UNSET) 기본 언어를 쓴다.
        lang = self._language if language is _UNSET else language
        audio = np.asarray(pcm, dtype=np.float32)
        kw = {}
        if self._initial_prompt and lang == self._language:
            kw["initial_prompt"] = self._initial_prompt  # 통역 자동감지 땐 미적용
        result = mlx_whisper.transcribe(
            audio, path_or_hf_repo=self._repo, language=lang,
            condition_on_previous_text=False,  # 이전 텍스트 조건화로 인한 환각 방지
            **kw,
        )
        return result["text"].strip()
