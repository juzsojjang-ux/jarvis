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
               voice: str | None = None, name: str | None = None,
               ptt_key: str | None = None) -> None:
    p = Path(path) if path else DEFAULT_SETUP_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    data = load_setup(p)
    data.update({"brain_provider": provider, "configured": True})
    if voice is not None:
        data["voice"] = voice           # "jarvis" | VOICE_PRESETS의 키
    if name is not None:
        data["assistant_name"] = name.strip() or "자비스"
    if ptt_key is not None and ptt_key in PTT_KEYS:
        data["ptt_key"] = ptt_key       # 마이크(말하기) 키 — pynput Key 이름
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


# 보이스 프리셋 — 셋업 UI 선택지. "jarvis"는 기본 체인(개인=Pocket 클론,
# 배포=edge→ONNX 음색)을 그대로 둔다. 나머지는 edge-tts 단독(음색 변환 없음).
# 마이크(말하기) 키 후보 — pynput keyboard.Key 이름 → 표시 라벨. 첫 설정에서 고른다.
PTT_KEYS: dict[str, str] = {
    "alt_r": "오른쪽 Alt (기본)",
    "alt_l": "왼쪽 Alt",
    "ctrl_r": "오른쪽 Ctrl",
    "ctrl_l": "왼쪽 Ctrl",
    "shift_r": "오른쪽 Shift",
    "cmd_r": "오른쪽 Cmd (맥)",
    "space": "스페이스바",
}

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
    ptt = (s.get("ptt_key") or "").strip()
    if ptt in PTT_KEYS:
        target.setdefault("JARVIS_PTT_KEY", ptt)


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
        # claude는 키가 아니라 CLI 로그인이 자격. 로그인이 안 돼 있으면(설정 파일만
        # 남은 다른 컴퓨터 등) '미설정'으로 봐서 첫 설정 화면을 다시 띄운다 — 그래야
        # 두뇌가 '없음'으로 죽지 않고 사용자가 로그인 버튼을 누를 수 있다.
        from jarvis.setup.login import claude_logged_in
        return claude_logged_in()
    if prov == "gpt":
        from jarvis.brain.codex_auth import is_codex_logged_in
        return is_codex_logged_in()
    return bool(get_key(prov))  # gemini → keyring key
