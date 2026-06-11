import numpy as np
from jarvis.stt.faster_whisper_stt import FasterWhisperSTT, _UNSET


class _Seg:
    def __init__(self, text): self.text = text


class _FakeModel:
    def __init__(self): self.last_lang = "SENTINEL"
    def transcribe(self, audio, language=None):
        self.last_lang = language
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
            def transcribe(self, audio, language=None): raise RuntimeError("x")
        return _M()
    s = FasterWhisperSTT("repo", model_factory=boom_factory)
    assert s.transcribe(np.zeros(16000, dtype=np.float32)) == ""
