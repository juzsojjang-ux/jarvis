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


def test_wake_word_defaults():
    s = Settings()
    assert s.wake_enabled is True
    assert "자비스" in s.wake_words and "jarvis" in s.wake_words
    assert s.follow_up_s == 8.0
    assert 0.0 < s.wake_vad_threshold < 1.0
    assert s.wake_silence_ms >= 300
    assert s.wake_max_utterance_s == 30.0
    assert s.wake_echo_cooldown_s == 0.5
    assert s.wake_min_speech_ms == 300
    assert s.wake_pre_roll_ms == 320
    assert s.vad_model_path.endswith("silero_vad.onnx")


def test_proactive_defaults():
    s = Settings()
    assert s.proactive_enabled is True
    assert s.battery_warn_levels == [20, 10, 5]
    assert s.reminder_lead_min == 10 and s.event_lead_min == 10
    assert s.greet_cooldown_h == 4.0
    assert s.briefing_expire_h == 2.0
    assert s.proactive_cooldown_min == 10
    assert s.proactive_late_night is False


def test_interpret_defaults():
    s = Settings()
    assert s.interpret_enabled is True
    assert s.interpret_ko_voice == "Yuna"


def test_screen_control_defaults():
    s = Settings()
    assert s.screen_control_ttl_s == 300.0


def test_remote_defaults():
    s = Settings()
    assert s.remote_enabled is True
    assert s.remote_host == "0.0.0.0"
    assert s.remote_port == 8790
