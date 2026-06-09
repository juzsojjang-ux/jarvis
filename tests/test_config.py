import pytest

import jarvis.core.config as cfg
from jarvis.core.config import Settings


def test_defaults():
    s = Settings()
    assert s.model_task == "claude-opus-4-8"
    assert s.model_conversational == "claude-haiku-4-5"
    assert s.ptt_key == "alt_r"
    assert s.stt_repo == "mlx-community/whisper-large-v3-turbo"
    assert s.language == "ko"
    assert s.playback_rate == 48000
    assert s.persona_path.name == "persona_ko.md"


def test_api_key_from_keyring(monkeypatch):
    monkeypatch.setattr(cfg.keyring, "get_password", lambda svc, usr: "sk-ant-test")
    assert Settings().api_key == "sk-ant-test"


def test_api_key_missing_raises(monkeypatch):
    monkeypatch.setattr(cfg.keyring, "get_password", lambda svc, usr: None)
    with pytest.raises(RuntimeError):
        _ = Settings().api_key
