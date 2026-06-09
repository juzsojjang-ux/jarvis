from jarvis.core.config import Settings


def test_m2_backend_defaults():
    f = Settings.model_fields
    # "auto": real JARVIS voice (XTTS clone) when .venv-xtts + reference exist, else say.
    assert f["tts_backend"].default == "auto"
    # "auto": JARVIS timbre auto-activates when voice_models/jarvis.pth + .venv-rvc exist.
    assert f["vc_backend"].default == "auto"
    assert f["rvc_sample_rate"].default == 40000
