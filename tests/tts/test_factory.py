import types

import pytest

from jarvis.tts.factory import make_tts
from jarvis.tts.melotts_kr import MeloTTSKR
from jarvis.tts.pocket_tts import PocketTTS
from jarvis.tts.system_say import SystemSayTTS
from jarvis.tts.xtts_kr import XTTSBackend


def _s(**kw):
    base = dict(tts_backend="say", tts_worker_python="/nonexistent/.venv-tts/bin/python",
                pocket_python="/nonexistent/.venv-pocket/bin/python",
                pocket_ref_path="/nonexistent/jarvis_ref.wav",
                xtts_python="/nonexistent/.venv-xtts/bin/python",
                xtts_ref_path="/nonexistent/jarvis_ref.wav", xtts_device="cpu",
                rvc_model_path="/nonexistent/voice_models/jarvis.pth",
                rvc_python="/nonexistent/.venv-rvc/bin/python",
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


def test_make_tts_pocket(tmp_path):
    py, ref = _ready(tmp_path)
    tts = make_tts(_s(tts_backend="pocket", pocket_python=py, pocket_ref_path=ref))
    assert isinstance(tts, PocketTTS) and tts._cmd[1:] == ["-m", "jarvis.tts.pocket_worker"]
    assert tts.sample_rate == 24000 and tts._env["JARVIS_POCKET_REF"] == ref


def test_pocket_falls_back_to_auto_when_not_ready():
    # tts_backend="pocket" but .venv-pocket absent -> auto -> say (nothing else ready)
    assert isinstance(make_tts(_s(tts_backend="pocket")), SystemSayTTS)


def test_auto_prefers_pocket_over_everything(tmp_path):
    py, ref = _ready(tmp_path)
    tts = make_tts(_s(tts_backend="auto", pocket_python=py, pocket_ref_path=ref))
    assert isinstance(tts, PocketTTS)


def test_auto_falls_back_to_say_when_not_ready():
    assert isinstance(make_tts(_s(tts_backend="auto")), SystemSayTTS)


def test_auto_prefers_melotts_when_rvc_chain_ready(tmp_path):
    # trained jarvis.pth + .venv-rvc + .venv-tts present -> native-Korean MeloTTS
    # feeds the RVC timbre conversion (beats cross-lingual XTTS).
    pth = tmp_path / "jarvis.pth"
    pth.write_bytes(b"x")
    rvc_py = tmp_path / "rvc-python"
    rvc_py.write_text("")
    tts_py = tmp_path / "tts-python"
    tts_py.write_text("")
    xtts_py, ref = _ready(tmp_path)  # xtts ALSO ready — rvc chain must win
    tts = make_tts(_s(tts_backend="auto", rvc_model_path=str(pth),
                      rvc_python=str(rvc_py), tts_worker_python=str(tts_py),
                      xtts_python=xtts_py, xtts_ref_path=ref))
    assert isinstance(tts, MeloTTSKR) and not isinstance(tts, XTTSBackend)


def test_make_tts_unknown_raises():
    with pytest.raises(ValueError):
        make_tts(_s(tts_backend="bogus"))
