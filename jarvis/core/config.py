from pathlib import Path

import keyring
from pydantic_settings import BaseSettings, SettingsConfigDict

_PKG_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # protected_namespaces=() so model_task/model_conversational don't collide with pydantic's
    # reserved "model_" namespace.
    model_config = SettingsConfigDict(
        env_prefix="JARVIS_", extra="ignore", protected_namespaces=()
    )

    model_task: str = "claude-opus-4-8"
    model_conversational: str = "claude-haiku-4-5"
    ptt_key: str = "alt_r"
    stt_repo: str = "mlx-community/whisper-large-v3-turbo"
    language: str = "ko"
    playback_rate: int = 48000
    memory_path: Path = Path.home() / ".jarvis" / "memory.md"
    persona_path: Path = _PKG_ROOT / "brain" / "persona_ko.md"
    keyring_service: str = "jarvis"
    keyring_user: str = "anthropic_api_key"

    # --- M2 voice backends ---
    tts_backend: str = "say"          # "say" (macOS say, M1 backend) | "melotts" (M2)
    vc_backend: str = "null"          # "null" (identity, M1 backend) | "rvc" (M2)
    tts_worker_python: str = "~/jarvis/.venv-tts/bin/python"
    rvc_model_path: str = "~/jarvis/voice_models/jarvis.pth"
    rvc_index_path: str = "~/jarvis/voice_models/jarvis.index"
    rvc_sample_rate: int = 40000
    rvc_index_rate: float = 0.75
    rvc_f0_up: int = 0

    @property
    def api_key(self) -> str:
        key = keyring.get_password(self.keyring_service, self.keyring_user)
        if not key:
            raise RuntimeError(
                "Anthropic API key not in keyring. Set it once with:\n"
                "  python -c \"import keyring; "
                "keyring.set_password('jarvis', 'anthropic_api_key', 'sk-ant-...')\""
            )
        return key
