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

    # Brain backend: "subscription" (Claude Pro/Max login via claude-agent-sdk — NO API
    # key, no per-token bill) or "api" (Anthropic API key + local tool loop).
    brain_backend: str = "subscription"
    subscription_model: str = ""        # "" = Claude Code's default plan model
    model_task: str = "claude-opus-4-8"          # api backend only
    model_conversational: str = "claude-haiku-4-5"  # api backend only
    ptt_key: str = "alt_r"
    stt_repo: str = "mlx-community/whisper-large-v3-turbo"
    language: str = "ko"
    playback_rate: int = 48000
    memory_path: Path = Path.home() / ".jarvis" / "memory.md"
    persona_path: Path = _PKG_ROOT / "brain" / "persona_ko.md"
    keyring_service: str = "jarvis"
    keyring_user: str = "anthropic_api_key"

    # --- M2 voice backends ---
    # "auto": real JARVIS voice (XTTS zero-shot clone) when .venv-xtts + a reference wav
    # exist, else macOS "say". Also: "xtts" | "melotts" | "say".
    tts_backend: str = "auto"
    xtts_python: str = "~/jarvis/.venv-xtts/bin/python"
    xtts_ref_path: str = "~/jarvis/voice_models/jarvis_ref.wav"
    xtts_device: str = "cpu"          # "cpu" (safe) | "mps" (faster, occasionally flaky)
    # "auto" (default): JARVIS timbre auto-activates when voice_models/jarvis.pth is
    # present AND the .venv-rvc runtime exists; otherwise the MeloTTS Korean voice
    # plays. "null" forces MeloTTS-only; "rvc" forces RVC (warns + falls back if the
    # model is missing). Drop-in readiness lives in jarvis/vc/resolve.py + factory.py.
    vc_backend: str = "auto"          # "auto" | "null" | "rvc"
    tts_worker_python: str = "~/jarvis/.venv-tts/bin/python"
    # Isolated RVC inference interpreter (mirrors .venv-tts). The factory builds
    # rvc_cmd = [rvc_python, jarvis/vc/rvc_infer_cli.py]. Created by setup_rvc.sh.
    rvc_python: str = "~/jarvis/.venv-rvc/bin/python"
    rvc_model_path: str = "~/jarvis/voice_models/jarvis.pth"
    rvc_index_path: str = "~/jarvis/voice_models/jarvis.index"
    rvc_sample_rate: int = 40000
    rvc_index_rate: float = 0.75
    rvc_f0_up: int = 0

    # --- HUD: movie-style JARVIS ring interface (Avengers look) ---
    hud_enabled: bool = True           # run the local HUD server (state/level over SSE)
    hud_host: str = "127.0.0.1"
    hud_port: int = 8787
    hud_overlay: bool = True           # native macOS overlay (transparent) — not a browser
    hud_open_browser: bool = False     # fallback: open the HUD in the default browser

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
