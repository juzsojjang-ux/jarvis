import numpy as np
from jarvis.stt.faster_whisper_stt import FasterWhisperSTT, _UNSET


class _Seg:
    def __init__(self, text): self.text = text


class _FakeModel:
    def __init__(self):
        self.last_lang = "SENTINEL"
        self.last_kwargs = {}
    def transcribe(self, audio, language=None, **kw):
        self.last_lang = language
        self.last_kwargs = kw
        return [_Seg("안녕"), _Seg(" 하세요")], object()


def _stt(**kw):
    fake = _FakeModel()
    s = FasterWhisperSTT("repo", model_factory=lambda r, d, c: fake, **kw)
    return s, fake


def test_transcribe_joins_segments():
    s, _ = _stt()
    assert s.transcribe(np.zeros(16000, dtype=np.float32)) == "안녕 하세요"


def test_unset_uses_default_language():
    s, fake = _stt(language="ko")
    s.transcribe(np.zeros(8000, dtype=np.float32))
    assert fake.last_lang == "ko"


def test_explicit_none_preserved_for_autodetect():
    s, fake = _stt(language="ko")
    s.transcribe(np.zeros(8000, dtype=np.float32), language=None)
    assert fake.last_lang is None  # 자동감지 — ko로 뭉개지면 안 됨


def test_transcribe_failure_returns_empty():
    def boom_factory(r, d, c):
        class _M:
            def transcribe(self, audio, language=None, **kw): raise RuntimeError("x")
        return _M()
    s = FasterWhisperSTT("repo", model_factory=boom_factory)
    assert s.transcribe(np.zeros(16000, dtype=np.float32)) == ""


def test_initial_prompt_applied_for_default_language_only():
    s, fake = _stt(language="ko", initial_prompt="자비스, 화면 제어 모드")
    s.transcribe(np.zeros(8000, dtype=np.float32))
    assert fake.last_kwargs.get("initial_prompt") == "자비스, 화면 제어 모드"
    # 통역 자동감지(None)나 다른 언어엔 한국어 프롬프트를 적용하지 않는다.
    s.transcribe(np.zeros(8000, dtype=np.float32), language=None)
    assert "initial_prompt" not in fake.last_kwargs
