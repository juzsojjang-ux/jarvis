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


def save_setup(provider: str, path: Path | None = None) -> None:
    p = Path(path) if path else DEFAULT_SETUP_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(
        json.dumps({"brain_provider": provider, "configured": True}, ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(tmp, p)


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
    return bool(get_key(prov))
