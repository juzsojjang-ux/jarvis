import types

from jarvis.tts.edge_tts_backend import EdgeTTS
from jarvis.tts.factory import make_tts


def _s(**kw):
    base = dict(
        tts_backend="say",
        tts_worker_python="/nonexistent/.venv-tts/bin/python",
        pocket_python="/nonexistent/.venv-pocket/bin/python",
        pocket_ref_path="/nonexistent/jarvis_ref.wav",
        xtts_python="/nonexistent/.venv-xtts/bin/python",
        xtts_ref_path="/nonexistent/jarvis_ref.wav",
        xtts_device="cpu",
        rvc_model_path="/nonexistent/voice_models/jarvis.pth",
        rvc_python="/nonexistent/.venv-rvc/bin/python",
        language="ko",
        edge_tts_voice="en-GB-RyanNeural",
    )
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_make_tts_edge_returns_edge_tts():
    tts = make_tts(_s(tts_backend="edge"))
    assert isinstance(tts, EdgeTTS)


def test_make_tts_edge_uses_configured_voice():
    tts = make_tts(_s(tts_backend="edge", edge_tts_voice="ko-KR-InJoonNeural"))
    assert isinstance(tts, EdgeTTS)
    assert tts._voice == "ko-KR-InJoonNeural"


def test_make_tts_edge_default_voice():
    tts = make_tts(_s(tts_backend="edge"))
    assert tts._voice == "en-GB-RyanNeural"
    assert tts.sample_rate == 24000
