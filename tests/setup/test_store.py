"""tests/setup/test_store.py — store.py 단위 테스트.

모든 테스트는 임시 경로를 쓰고 keyring을 monkeypatch해서
실제 ~/.jarvis 또는 실제 keyring에 절대 쓰지 않는다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import jarvis.setup.store as store_mod
from jarvis.setup.store import (
    configured_provider,
    get_key,
    is_configured,
    load_setup,
    save_key,
    save_setup,
)


# ---------------------------------------------------------------------------
# 공용 픽스처
# ---------------------------------------------------------------------------

@pytest.fixture()
def fake_keyring(monkeypatch):
    """keyring 호출을 인메모리 dict으로 대체한다."""
    mem: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(
        "jarvis.setup.store.keyring.set_password",
        lambda s, u, k: mem.__setitem__((s, u), k),
    )
    monkeypatch.setattr(
        "jarvis.setup.store.keyring.get_password",
        lambda s, u: mem.get((s, u)),
    )
    return mem


@pytest.fixture()
def tmp_setup(tmp_path):
    """임시 setup.json 경로를 반환한다."""
    return tmp_path / "setup.json"


# ---------------------------------------------------------------------------
# load_setup / save_setup 왕복
# ---------------------------------------------------------------------------

def test_load_returns_empty_when_missing(tmp_setup):
    assert load_setup(tmp_setup) == {}


def test_roundtrip_save_load(tmp_setup):
    save_setup("gemini", tmp_setup)
    data = load_setup(tmp_setup)
    assert data["brain_provider"] == "gemini"
    assert data["configured"] is True


def test_save_creates_parent_dirs(tmp_path):
    deep = tmp_path / "a" / "b" / "setup.json"
    save_setup("gpt", deep)
    assert deep.exists()


def test_atomic_write_no_tmp_leftover(tmp_setup):
    """원자 교체 후 .tmp 파일이 남지 않아야 한다."""
    save_setup("claude", tmp_setup)
    tmp_file = Path(str(tmp_setup) + ".tmp")
    assert not tmp_file.exists()


# ---------------------------------------------------------------------------
# configured_provider
# ---------------------------------------------------------------------------

def test_configured_provider_none_when_missing(tmp_setup):
    assert configured_provider(tmp_setup) is None


def test_configured_provider_none_when_configured_false(tmp_setup):
    import json

    tmp_setup.write_text(
        json.dumps({"brain_provider": "gemini", "configured": False}), encoding="utf-8"
    )
    assert configured_provider(tmp_setup) is None


def test_configured_provider_returns_value(tmp_setup):
    save_setup("gpt", tmp_setup)
    assert configured_provider(tmp_setup) == "gpt"


# ---------------------------------------------------------------------------
# is_configured
# ---------------------------------------------------------------------------

def test_is_configured_false_when_no_file(tmp_setup, fake_keyring):
    assert is_configured(tmp_setup) is False


def test_is_configured_claude_true_without_key(tmp_setup, fake_keyring):
    """claude는 구독 로그인이므로 키 없이도 configured=True."""
    save_setup("claude", tmp_setup)
    assert is_configured(tmp_setup) is True


def test_is_configured_gemini_false_without_key(tmp_setup, fake_keyring):
    save_setup("gemini", tmp_setup)
    assert is_configured(tmp_setup) is False


def test_is_configured_gemini_true_after_save_key(tmp_setup, fake_keyring):
    save_setup("gemini", tmp_setup)
    save_key("gemini", "AIza-fake-key")
    assert is_configured(tmp_setup) is True


def test_is_configured_gpt_false_when_codex_not_logged_in(tmp_setup, fake_keyring, monkeypatch):
    """GPT: codex 미로그인 → is_configured False."""
    monkeypatch.setattr("jarvis.brain.codex_auth.is_codex_logged_in", lambda path=None: False)
    save_setup("gpt", tmp_setup)
    assert is_configured(tmp_setup) is False


def test_is_configured_gpt_true_when_codex_logged_in(tmp_setup, fake_keyring, monkeypatch):
    """GPT: codex 로그인 → is_configured True (키 불필요)."""
    monkeypatch.setattr("jarvis.brain.codex_auth.is_codex_logged_in", lambda path=None: True)
    save_setup("gpt", tmp_setup)
    assert is_configured(tmp_setup) is True


# ---------------------------------------------------------------------------
# save_key / get_key
# ---------------------------------------------------------------------------

def test_save_key_gemini(fake_keyring):
    save_key("gemini", "AIza-test")
    assert fake_keyring[("jarvis", "gemini_api_key")] == "AIza-test"


def test_save_key_gpt(fake_keyring):
    save_key("gpt", "sk-test")
    assert fake_keyring[("jarvis", "openai_api_key")] == "sk-test"


def test_save_key_claude_noop(fake_keyring):
    """claude는 keyring 사용자가 없으므로 keyring에 아무것도 저장하지 않는다."""
    save_key("claude", "ignored")
    assert len(fake_keyring) == 0


def test_get_key_returns_none_when_missing(fake_keyring):
    assert get_key("gemini") is None


def test_get_key_returns_saved_value(fake_keyring):
    save_key("gemini", "AIza-hello")
    assert get_key("gemini") == "AIza-hello"


def test_get_key_claude_returns_none(fake_keyring):
    """claude는 keyring 사용자가 없으므로 None을 반환한다."""
    assert get_key("claude") is None


def test_save_key_empty_string_noop(fake_keyring):
    """빈 키는 저장하지 않아야 한다."""
    save_key("gemini", "")
    assert len(fake_keyring) == 0
