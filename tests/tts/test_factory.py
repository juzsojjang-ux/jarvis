import types

import pytest

from jarvis.tts.factory import make_tts
from jarvis.tts.melotts_kr import MeloTTSKR
from jarvis.tts.system_say import SystemSayTTS


def _s(**kw):
    base = dict(tts_backend="say", tts_worker_python="~/jarvis/.venv-tts/bin/python")
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_make_tts_say():
    assert isinstance(make_tts(_s(tts_backend="say")), SystemSayTTS)


def test_make_tts_melotts():
    tts = make_tts(_s(tts_backend="melotts"))
    assert isinstance(tts, MeloTTSKR) and tts._cmd[1:] == ["-m", "jarvis.tts.tts_worker"]


def test_make_tts_unknown_raises():
    with pytest.raises(ValueError):
        make_tts(_s(tts_backend="bogus"))
