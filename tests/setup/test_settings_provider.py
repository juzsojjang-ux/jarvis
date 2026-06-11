"""tests/setup/test_settings_provider.py — Settings가 저장된 brain_provider를 반영하는지 확인.

환경변수 주입 방식 테스트:
  configured_provider()의 반환값을 os.environ.setdefault("JARVIS_BRAIN_PROVIDER", ...)로
  주입하면 Settings()가 그 값을 읽는다(env가 최우선).

실제 ~/.jarvis 를 건드리지 않는다 — 임시 경로에 setup.json을 쓰고,
configured_provider 를 monkeypatch해서 그 값을 반환하게 한다.
"""
from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """테스트 후 JARVIS_BRAIN_PROVIDER 환경변수가 오염되지 않도록 격리한다."""
    monkeypatch.delenv("JARVIS_BRAIN_PROVIDER", raising=False)
    yield


def test_settings_picks_up_env_brain_provider(monkeypatch):
    """JARVIS_BRAIN_PROVIDER 환경변수를 직접 설정하면 Settings()가 반영한다."""
    monkeypatch.setenv("JARVIS_BRAIN_PROVIDER", "gemini")
    from jarvis.core.config import Settings
    s = Settings()
    assert s.brain_provider == "gemini"


def test_settings_env_injection_from_configured_provider(monkeypatch, tmp_path):
    """configured_provider()를 monkeypatch해서 env setdefault 흐름을 검증한다."""
    import jarvis.setup.store as store_mod

    # configured_provider가 "gpt"를 반환하도록 패치
    monkeypatch.setattr(store_mod, "configured_provider", lambda path=None: "gpt")

    # __main__ 부팅 흐름을 인라인으로 재현
    saved = store_mod.configured_provider()
    if saved:
        os.environ.setdefault("JARVIS_BRAIN_PROVIDER", saved)

    from jarvis.core.config import Settings
    s = Settings()
    assert s.brain_provider == "gpt"


def test_env_takes_priority_over_stored_value(monkeypatch, tmp_path):
    """JARVIS_BRAIN_PROVIDER 환경변수가 이미 있으면 setdefault는 그것을 유지한다."""
    import jarvis.setup.store as store_mod

    monkeypatch.setenv("JARVIS_BRAIN_PROVIDER", "claude")
    monkeypatch.setattr(store_mod, "configured_provider", lambda path=None: "gemini")

    saved = store_mod.configured_provider()
    if saved:
        os.environ.setdefault("JARVIS_BRAIN_PROVIDER", saved)  # "claude"가 이미 있으므로 무시됨

    from jarvis.core.config import Settings
    s = Settings()
    assert s.brain_provider == "claude"


def test_save_and_retrieve_provider_roundtrip(tmp_path, monkeypatch):
    """save_setup → configured_provider → env → Settings 전체 경로를 검증한다."""
    from jarvis.setup.store import save_setup, configured_provider

    setup_path = tmp_path / "setup.json"
    save_setup("gemini", setup_path)

    # configured_provider를 해당 임시 경로를 쓰도록 monkeypatch
    import jarvis.setup.store as store_mod
    monkeypatch.setattr(store_mod, "configured_provider", lambda path=None: configured_provider(setup_path))

    saved = store_mod.configured_provider()
    assert saved == "gemini"

    os.environ.setdefault("JARVIS_BRAIN_PROVIDER", saved)

    from jarvis.core.config import Settings
    s = Settings()
    assert s.brain_provider == "gemini"
