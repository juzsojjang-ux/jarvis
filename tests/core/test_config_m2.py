from jarvis.core.config import Settings


def test_m2_backend_defaults():
    f = Settings.model_fields
    # "pocket": Kyutai Pocket TTS English JARVIS clone (user's chosen voice).
    assert f["tts_backend"].default == "pocket"
    assert f["reply_language"].default == "en"
    # "null": Pocket already IS the voice; RVC would wreck it.
    assert f["vc_backend"].default == "null"
    assert f["rvc_sample_rate"].default == 40000
    # similarity-first: timbre pulled hard to JARVIS; -12 = measured MeloTTS-KR(210Hz)
    # -> JARVIS(108Hz) octave correction.
    assert f["rvc_index_rate"].default == 0.9
    assert f["rvc_f0_up"].default == -12
