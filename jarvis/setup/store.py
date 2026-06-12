"""첫 실행 설정 영구 저장 — 선택은 ~/.jarvis/setup.json, 키는 keyring."""
from __future__ import annotations

import json
import os
from pathlib import Path

import keyring

DEFAULT_SETUP_PATH = Path.home() / ".jarvis" / "setup.json"
KEYRING_SERVICE = "jarvis"
_KEY_USER = {"gemini": "gemini_api_key", "gpt": "openai_api_key"}


def load_setup(path: Path | None = None) -> dict:
    p = Path(path) if path else DEFAULT_SETUP_PATH
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - 없거나 손상 → 빈 설정
        return {}


def save_setup(provider: str, path: Path | None = None, *,
               voice: str | None = None, name: str | None = None) -> None:
    p = Path(path) if path else DEFAULT_SETUP_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    data = load_setup(p)
    data.update({"brain_provider": provider, "configured": True})
    if voice is not None:
        data["voice"] = voice           # "jarvis" | VOICE_PRESETS의 키
    if name is not None:
        data["assistant_name"] = name.strip() or "자비스"
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


# 보이스 프리셋 — 셋업 UI 선택지. "jarvis"는 기본 체인(개인=Pocket 클론,
# 배포=edge→ONNX 음색)을 그대로 둔다. 나머지는 edge-tts 단독(음색 변환 없음).
VOICE_PRESETS: dict[str, dict[str, str]] = {
    "jarvis": {},
    # 자비스 음색 + 한국어 발화(한국어 네이티브 edge 음성 → ONNX 자비스 음색 변환)
    "jarvis_ko": {"JARVIS_TTS_BACKEND": "edge", "JARVIS_VC_BACKEND": "onnx",
                  "JARVIS_EDGE_TTS_VOICE": "ko-KR-InJoonNeural",
                  "JARVIS_REPLY_LANGUAGE": "ko"},
    "butler_en": {"JARVIS_TTS_BACKEND": "edge", "JARVIS_VC_BACKEND": "null",
                  "JARVIS_EDGE_TTS_VOICE": "en-GB-RyanNeural",
                  "JARVIS_REPLY_LANGUAGE": "en"},
    "male_us": {"JARVIS_TTS_BACKEND": "edge", "JARVIS_VC_BACKEND": "null",
                "JARVIS_EDGE_TTS_VOICE": "en-US-GuyNeural",
                "JARVIS_REPLY_LANGUAGE": "en"},
    "female_us": {"JARVIS_TTS_BACKEND": "edge", "JARVIS_VC_BACKEND": "null",
                  "JARVIS_EDGE_TTS_VOICE": "en-US-AriaNeural",
                  "JARVIS_REPLY_LANGUAGE": "en"},
    "male_ko": {"JARVIS_TTS_BACKEND": "edge", "JARVIS_VC_BACKEND": "null",
                "JARVIS_EDGE_TTS_VOICE": "ko-KR-InJoonNeural",
                "JARVIS_REPLY_LANGUAGE": "ko"},
    "female_ko": {"JARVIS_TTS_BACKEND": "edge", "JARVIS_VC_BACKEND": "null",
                  "JARVIS_EDGE_TTS_VOICE": "ko-KR-SunHiNeural",
                  "JARVIS_REPLY_LANGUAGE": "ko"},
}


def apply_setup_env(environ=None, path: Path | None = None) -> None:
    """저장된 보이스/이름 선택을 환경변수로 적용(부팅 시 1회). setdefault라
    사용자가 직접 지정한 JARVIS_* env가 항상 우선한다."""
    target = os.environ if environ is None else environ
    s = load_setup(path)
    for k, v in VOICE_PRESETS.get(s.get("voice", "jarvis"), {}).items():
        target.setdefault(k, v)
    name = (s.get("assistant_name") or "").strip()
    if name and name != "자비스":
        target.setdefault("JARVIS_ASSISTANT_NAME", name)
        # 웨이크워드도 새 이름으로(pydantic은 env의 JSON 리스트를 읽는다)
        target.setdefault("JARVIS_WAKE_WORDS", json.dumps([name], ensure_ascii=False))


def save_key(provider: str, key: str) -> None:
    user = _KEY_USER.get(provider)
    if user and key:
        keyring.set_password(KEYRING_SERVICE, user, key)


def get_key(provider: str) -> str | None:
    user = _KEY_USER.get(provider)
    return keyring.get_password(KEYRING_SERVICE, user) if user else None


def configured_provider(path: Path | None = None) -> str | None:
    s = load_setup(path)
    return s.get("brain_provider") if s.get("configured") else None


def is_configured(path: Path | None = None) -> bool:
    prov = configured_provider(path)
    if prov is None:
        return False
    if prov == "claude":
        return True  # 구독 로그인은 claude CLI가 관리
    if prov == "gpt":
        from jarvis.brain.codex_auth import is_codex_logged_in
        return is_codex_logged_in()
    return bool(get_key(prov))  # gemini → keyring key
