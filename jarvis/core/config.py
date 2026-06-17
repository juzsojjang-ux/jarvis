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

    # 어시스턴트 이름 — 웨이크워드·HUD 라벨·자칭에 쓰인다(첫 설정에서 변경 가능)
    assistant_name: str = "자비스"

    # 두뇌 프로바이더: 첫 실행에서 택1. "claude"(기본) | "gemini" | "gpt"
    # Gemini/GPT는 다음 sub-project에서 구현 예정 — 지금은 claude만 동작.
    brain_provider: str = "claude"  # 첫 실행에서 택1: claude/gemini/gpt
    gemini_model: str = "gemini-2.5-flash"  # Gemini 두뇌용 모델 이름
    gpt_model: str = "gpt-4o"              # GPT 두뇌용 모델 이름
    gpt_auth: str = "subscription"         # "subscription"(ChatGPT 구독, codex login) | "api_key"(유료 키)
    gpt_subscription_base_url: str = "https://chatgpt.com/backend-api/codex"
    gpt_subscription_model: str = "gpt-5.5"

    # Brain backend: "subscription" (Claude Pro/Max login via claude-agent-sdk — NO API
    # key, no per-token bill) or "api" (Anthropic API key + local tool loop).
    brain_backend: str = "subscription"
    # 기본 대화는 Sonnet(사용자 선택 — 빠른 첫음성, 실측 2.8s→1.3s). 깊은 사고가
    # 필요한 요청("최대 사고/think hard")만 deep_model(Opus)로 올린다.
    subscription_model: str = "claude-sonnet-4-6"
    deep_model: str = "claude-opus-4-8"
    # 앙상블(보조 두뇌 병렬 자문): off 기본 — 판단은 연동된 메인 두뇌가 한다.
    # 원하면 JARVIS_ENSEMBLE_MODE=deep(딥씽킹 턴)/always 로 켤 수 있다.
    ensemble_mode: str = "off"
    # 메인 두뇌 심화 사용: 평소 사고 예산 / 딥 트리거('최대 사고') 예산
    think_budget_normal: int = 4000
    think_budget_deep: int = 24000
    # 비맥 아침 브리핑 시각(시) — 맥은 첫 잠금해제가 브리핑을 겸한다
    briefing_hour: int = 8
    # 화면 감시 모드('화면 봐줘') 캡처 주기
    watch_interval_s: float = 5.0
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
    # pocket > melotts->RVC > xtts > say. Also force one: "pocket"|"xtts"|"melotts"|"say"|"edge".
    tts_backend: str = "pocket"
    # edge-tts (cross-platform, no API key): voice name used by the EdgeTTS backend.
    # "en-GB-RyanNeural" = British butler tone; swap to e.g. "ko-KR-InJoonNeural" for Korean.
    edge_tts_voice: str = "en-GB-RyanNeural"
    reply_language: str = "en"        # JARVIS replies in this language (pocket = English-only)
    pocket_python: str = "~/jarvis/.venv-pocket/bin/python"
    # Clean 16s continuous English JARVIS take — Pocket reproduces the sample's quality,
    # so a single clean reference clones more consistently than a concatenation.
    pocket_ref_path: str = "~/jarvis/voice_models/jarvis_en_ref.wav"
    # 배포 설치(upgrade_full_voice)가 가리키는 HF 캐시. 비어 있지 않으면 Pocket 워커
    # *프로세스에만* HF_HOME + HF_HUB_OFFLINE=1을 건다 — 게이트된 음색 가중치를 토큰
    # 없이 오프라인 로드(전역에 걸면 아직 캐시 안 된 Whisper STT 다운로드가 막힌다).
    pocket_hf_home: str = ""
    xtts_python: str = "~/jarvis/.venv-xtts/bin/python"
    xtts_ref_path: str = "~/jarvis/voice_models/jarvis_ref.wav"
    xtts_device: str = "cpu"          # "cpu" (safe) | "mps" (faster, occasionally flaky)
    # "auto" (default): JARVIS timbre auto-activates when voice_models/jarvis.pth is
    # present AND the .venv-rvc runtime exists; otherwise the MeloTTS Korean voice
    # plays. "null" forces MeloTTS-only; "rvc" forces RVC (warns + falls back if the
    # model is missing). Drop-in readiness lives in jarvis/vc/resolve.py + factory.py.
    # "null" while tts="pocket" (Pocket already IS the JARVIS voice; RVC would wreck it).
    # Set "auto" to re-enable the Korean MeloTTS->RVC chain (needs tts="melotts"/"auto").
    # "onnx": torch-free ONNX RVC (배포 번들 기본) — edge-tts → contentvec → synthesizer.
    vc_backend: str = "null"          # "auto" | "null" | "rvc" | "onnx"
    onnx_model_path: str = "~/jarvis/voice_models/jarvis.onnx"
    onnx_contentvec_path: str = "~/jarvis/voice_models/vec-768-layer-12.onnx"
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
    # STT가 "자비스"를 자주 변형해 듣는다(재비스/자비쓰/자 비스 등) — 흔한 오인식을
    # 함께 등록해 호출 누락을 막는다. '일어나'류는 사용자 요청 트리거.
    wake_words: list[str] = ["자비스", "쟈비스", "재비스", "자비쓰", "자뷔스",
                             "지비스", "jarvis", "일어나", "일어나봐"]
    follow_up_s: float = 8.0          # 답변 후 웨이크워드 없이 듣는 창
    # "자비스"만 부르면 바로 "네 주인님?"으로 막지 않고 이 시간(초)만큼 듣는다 —
    # 그 안에 '말을 시작하면' 명령으로 받는다(웨이크워드 생략). 정적이면 그제야 인사.
    wake_grace_s: float = 3.0
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
    trust_mode_ttl_s: float = 600.0  # "전권 위임 모드" 자동 만료(초) — 잊어도 닫힘

    # --- 크로스플랫폼 STT ---
    # "mlx": 애플 실리콘 최속(맥 기본). "faster": CTranslate2 CPU/CUDA(윈도우·리눅스).
    stt_backend: str = "mlx"
    # Whisper initial_prompt — 여기 등장한 어휘를 우선해 받아적는다(명령어 인식률↑).
    # 자비스 호출어·모드 명령·자주 쓰는 도구 표현을 나열한다.
    stt_initial_prompt: str = (
        "자비스, 화면 제어 모드 켜줘. 전권 위임 모드. 통역 모드. 패널에 보여줘. "
        "패널 꺼줘. 사용량 알려줘. 타이머. 미리알림. 캘린더. 클릭해줘. 입력해줘."
    )
    # faster-whisper 전용 quantization — int8(기본, 빠름) | float16 | float32
    faster_whisper_compute: str = "int8"

    # --- M7 아이폰 원격 명령 ---
    remote_enabled: bool = True
    remote_host: str = "0.0.0.0"   # LAN 수신(외부망은 Tailscale 권장 — 포트포워딩 비권장)
    remote_port: int = 8790

    # --- HUD: movie-style JARVIS ring interface (Avengers look) ---
    hud_enabled: bool = True           # run the local HUD server (state/level over SSE)
    hud_host: str = "127.0.0.1"
    hud_port: int = 8787
    hud_overlay: bool = True           # 네이티브 오버레이(맥 WKWebView/윈도우 전용 창)
    hud_open_browser: bool = False     # fallback: open the HUD in the default browser
    # 메뉴 막대(맥)/시스템 트레이(윈도우)에 '자비스 실행 중' 상태 아이콘 표시.
    tray_enabled: bool = True

    # --- 타자 입력(Ask) ---
    ask_enabled: bool = True
    ask_hotkey: str = "alt+space"   # 입력창 호출 단축키(설정에서 변경). 윈도우=ctrl+space

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
