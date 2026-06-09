import types

import pytest

from jarvis.tts.factory import make_tts
from jarvis.tts.melotts_kr import MeloTTSKR
from jarvis.tts.system_say import SystemSayTTS
from jarvis.tts.xtts_kr import XTTSBackend


def _s(**kw):
    base = dict(tts_backend="say", tts_worker_python="~/jarvis/.venv-tts/bin/python",
                xtts_python="/nonexistent/.venv-xtts/bin/python",
                xtts_ref_path="/nonexistent/jarvis_ref.wav", xtts_device="cpu",
                language="ko")
    base.update(kw)
    return types.SimpleNamespace(**base)


def _ready(tmp_path):
    py = tmp_path / "python"
    py.write_text("")
    ref = tmp_path / "jarvis_ref.wav"
    ref.write_bytes(b"x")
    return str(py), str(ref)


def test_make_tts_say():
    assert isinstance(make_tts(_s(tts_backend="say")), SystemSayTTS)


def test_make_tts_melotts():
    tts = make_tts(_s(tts_backend="melotts"))
    assert isinstance(tts, MeloTTSKR) and tts._cmd[1:] == ["-m", "jarvis.tts.tts_worker"]


def test_make_tts_xtts():
    tts = make_tts(_s(tts_backend="xtts"))
    assert isinstance(tts, XTTSBackend) and tts._cmd[1:] == ["-m", "jarvis.tts.xtts_worker"]
    assert tts.sample_rate == 24000


def test_auto_uses_xtts_when_runtime_and_ref_present(tmp_path):
    py, ref = _ready(tmp_path)
    tts = make_tts(_s(tts_backend="auto", xtts_python=py, xtts_ref_path=ref))
    assert isinstance(tts, XTTSBackend)
    assert tts._env["JARVIS_XTTS_REF"] == ref


def test_auto_falls_back_to_say_when_not_ready():
    assert isinstance(make_tts(_s(tts_backend="auto")), SystemSayTTS)


def test_make_tts_unknown_raises():
    with pytest.raises(ValueError):
        make_tts(_s(tts_backend="bogus"))
