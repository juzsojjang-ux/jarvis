from jarvis.core.config import Settings


def test_m2_backend_defaults():
    f = Settings.model_fields
    # "auto": real JARVIS voice (XTTS clone) when .venv-xtts + reference exist, else say.
    assert f["tts_backend"].default == "auto"
    # "auto": JARVIS timbre auto-activates when voice_models/jarvis.pth + .venv-rvc exist.
    assert f["vc_backend"].default == "auto"
    assert f["rvc_sample_rate"].default == 40000
    # similarity-first: timbre pulled hard to JARVIS; -12 = measured MeloTTS-KR(210Hz)
    # -> JARVIS(108Hz) octave correction.
    assert f["rvc_index_rate"].default == 0.9
    assert f["rvc_f0_up"].default == -12
