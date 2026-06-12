import types

import pytest

pytest.importorskip("mlx_whisper", reason="mlx는 애플 실리콘 전용 — 윈도우 CI 스킵")

from jarvis.stt.factory import make_stt
from jarvis.stt.mlx_whisper import MLXWhisperSTT
from jarvis.stt.faster_whisper_stt import FasterWhisperSTT


def _settings(**kw):
    base = dict(stt_backend="mlx", stt_repo="r", language="ko", faster_whisper_compute="int8")
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_make_stt_default_returns_mlx():
    s = make_stt(_settings())
    assert isinstance(s, MLXWhisperSTT)


def test_make_stt_mlx_explicit():
    s = make_stt(_settings(stt_backend="mlx"))
    assert isinstance(s, MLXWhisperSTT)


def test_make_stt_faster_returns_faster_whisper():
    s = make_stt(_settings(stt_backend="faster"))
    assert isinstance(s, FasterWhisperSTT)


def test_make_stt_faster_passes_compute_type():
    s = make_stt(_settings(stt_backend="faster", faster_whisper_compute="float16"))
    assert s._compute == "float16"


def test_make_stt_passes_language():
    s = make_stt(_settings(stt_backend="faster", language="en"))
    assert s._language == "en"
