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
    # Opus for accuracy (user preferred its quality over Sonnet). The instant spoken
    # acknowledgement masks Opus's first-token latency; "최대 사고/think hard" adds
    # extended thinking on top.
    subscription_model: str = "claude-opus-4-8"
    deep_model: str = "claude-opus-4-8"
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
    # "pocket": Kyutai Pocket TTS English JARVIS clone (user's pick — sounds most like
    # the real JARVIS); falls back to "auto" if .venv-pocket isn't set up. "auto" picks
    # pocket > melotts->RVC > xtts > say. Also force one: "pocket"|"xtts"|"melotts"|"say".
    tts_backend: str = "pocket"
    reply_language: str = "en"        # JARVIS replies in this language (pocket = English-only)
    pocket_python: str = "~/jarvis/.venv-pocket/bin/python"
    # Clean 16s continuous English JARVIS take — Pocket reproduces the sample's quality,
    # so a single clean reference clones more consistently than a concatenation.
    pocket_ref_path: str = "~/jarvis/voice_models/jarvis_en_ref.wav"
    xtts_python: str = "~/jarvis/.venv-xtts/bin/python"
    xtts_ref_path: str = "~/jarvis/voice_models/jarvis_ref.wav"
    xtts_device: str = "cpu"          # "cpu" (safe) | "mps" (faster, occasionally flaky)
    # "auto" (default): JARVIS timbre auto-activates when voice_models/jarvis.pth is
    # present AND the .venv-rvc runtime exists; otherwise the MeloTTS Korean voice
    # plays. "null" forces MeloTTS-only; "rvc" forces RVC (warns + falls back if the
    # model is missing). Drop-in readiness lives in jarvis/vc/resolve.py + factory.py.
    # "null" while tts="pocket" (Pocket already IS the JARVIS voice; RVC would wreck it).
    # Set "auto" to re-enable the Korean MeloTTS->RVC chain (needs tts="melotts"/"auto").
    vc_backend: str = "null"          # "auto" | "null" | "rvc"
    tts_worker_python: str = "~/jarvis/.venv-tts/bin/python"
    # Isolated RVC inference interpreter (mirrors .venv-tts). The factory builds
    # rvc_cmd = [rvc_python, jarvis/vc/rvc_infer_cli.py]. Created by setup_rvc.sh.
    rvc_python: str = "~/jarvis/.venv-rvc/bin/python"
    rvc_model_path: str = "~/jarvis/voice_models/jarvis.pth"
    rvc_index_path: str = "~/jarvis/voice_models/jarvis.index"
    rvc_sample_rate: int = 40000
    # SIMILARITY-FIRST defaults (user priority: Korean speech must sound maximally like
    # JARVIS). index_rate 0.9 pulls timbre hard toward the trained voice. f0_up -12 is
    # MEASURED, not guessed: MeloTTS-KR's default speaker has median f0 210.1 Hz vs the
    # JARVIS reference 108.2 Hz (+11.5 semitones) — without the octave-down shift the
    # output would be JARVIS timbre at a female pitch.
    rvc_index_rate: float = 0.9
    rvc_f0_up: int = -12

    # --- M3 웨이크워드 + 연속대화 (실제 자비스 1단계) ---
    # 마이크 상시-온(전부 로컬 처리). "자비스"로 시작하는 발화만 명령으로 쓰고
    # 나머지 변환 텍스트는 즉시 폐기한다(저장·로그 금지). PTT는 백업으로 공존.
    wake_enabled: bool = True
    wake_words: list[str] = ["자비스", "쟈비스", "jarvis"]
    follow_up_s: float = 8.0          # 답변 후 웨이크워드 없이 듣는 창
    wake_vad_threshold: float = 0.5   # silero 말소리 확률 문턱값
    wake_silence_ms: int = 800        # 이만큼 조용하면 발화 종료
    wake_max_utterance_s: float = 30.0  # 긴 대화를 통째로 변환하는 낭비 방지 캡
    wake_echo_cooldown_s: float = 0.5   # 자비스 발화 직후 자기 잔향 무시(스피커 환경이면 ↑)
    wake_min_speech_ms: int = 300       # 이보다 짧은 소리는 발화로 안 침
    wake_pre_roll_ms: int = 320         # 발화 직전 보존 구간 — "자비스" 첫 음절 잘림 방지
    vad_model_path: str = "~/jarvis/voice_models/silero_vad.onnx"

    # --- M4 능동적 자비스 (2단계) ---
    # 먼저 말 거는 자비스: 브리핑/배터리/미리알림·일정/인사. 대화 중엔 보류.
    proactive_enabled: bool = True
    battery_warn_levels: list[int] = [20, 10, 5]  # 하향 돌파마다 1회 경고
    reminder_lead_min: int = 10        # 미리알림 due 몇 분 전에 알릴지
    event_lead_min: int = 10           # 캘린더 일정 시작 몇 분 전에 알릴지
    greet_cooldown_h: float = 4.0      # 복귀 인사 최소 간격
    briefing_expire_h: float = 2.0     # 묵은 브리핑 폐기
    proactive_cooldown_min: int = 10   # 같은 종류 알림 최소 간격
    proactive_late_night: bool = False  # 새벽 2시 "주무시죠" 한마디(기본 꺼짐)

    # --- M5 정보 팩 (3b) ---
    interpret_enabled: bool = True        # "통역 모드" 사용 가능
    interpret_ko_voice: str = "Yuna"      # 통역 한국어 출력 보이스(macOS say)

    # --- M6 화면 시야+제어 (3c) ---
    screen_control_ttl_s: float = 300.0  # "화면 제어 모드" 자동 만료(초) — 켠 채 잊기 방지

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
