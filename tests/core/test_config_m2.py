from jarvis.core.config import Settings


def test_m2_backend_defaults():
    f = Settings.model_fields
    assert f["tts_backend"].default == "say"
    assert f["vc_backend"].default == "null"
    assert f["rvc_sample_rate"].default == 40000
