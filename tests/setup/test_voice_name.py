"""보이스 프리셋·이름 변경(setup) + 외부 MCP 로더 테스트."""
from __future__ import annotations

import json

from jarvis.setup.store import VOICE_PRESETS, apply_setup_env, load_setup, save_setup
from jarvis.tools.external_mcp import load_external_servers


# --- save/load 라운드트립 -----------------------------------------------------
def test_save_setup_with_voice_and_name(tmp_path):
    p = tmp_path / "setup.json"
    save_setup("claude", p, voice="male_ko", name="프라이데이")
    s = load_setup(p)
    assert s["voice"] == "male_ko" and s["assistant_name"] == "프라이데이"
    assert s["configured"] is True


def test_save_setup_backward_compatible(tmp_path):
    p = tmp_path / "setup.json"
    save_setup("gemini", p)  # 구형 호출(보이스/이름 없음)
    s = load_setup(p)
    assert s["brain_provider"] == "gemini" and "voice" not in s


# --- apply_setup_env ----------------------------------------------------------
def test_voice_preset_applied_to_env(tmp_path):
    p = tmp_path / "setup.json"
    save_setup("claude", p, voice="female_ko")
    env: dict = {}
    apply_setup_env(env, p)
    assert env["JARVIS_EDGE_TTS_VOICE"] == "ko-KR-SunHiNeural"
    assert env["JARVIS_REPLY_LANGUAGE"] == "ko"
    assert env["JARVIS_VC_BACKEND"] == "null"


def test_jarvis_voice_keeps_defaults(tmp_path):
    p = tmp_path / "setup.json"
    save_setup("claude", p, voice="jarvis", name="자비스")
    env: dict = {}
    apply_setup_env(env, p)
    assert env == {}  # 기본 체인 유지 — 아무것도 강제하지 않음


def test_custom_name_sets_wake_words(tmp_path):
    p = tmp_path / "setup.json"
    save_setup("claude", p, name="프라이데이")
    env: dict = {}
    apply_setup_env(env, p)
    assert env["JARVIS_ASSISTANT_NAME"] == "프라이데이"
    assert json.loads(env["JARVIS_WAKE_WORDS"]) == ["프라이데이"]


def test_user_env_wins_over_preset(tmp_path):
    p = tmp_path / "setup.json"
    save_setup("claude", p, voice="male_us")
    env = {"JARVIS_EDGE_TTS_VOICE": "en-GB-SoniaNeural"}  # 사용자 직접 지정
    apply_setup_env(env, p)
    assert env["JARVIS_EDGE_TTS_VOICE"] == "en-GB-SoniaNeural"


def test_all_presets_have_consistent_keys():
    for key, preset in VOICE_PRESETS.items():
        if key == "jarvis":
            assert preset == {}
            continue
        assert preset["JARVIS_TTS_BACKEND"] == "edge"
        assert "JARVIS_EDGE_TTS_VOICE" in preset


# --- 외부 MCP 로더 -------------------------------------------------------------
def test_external_mcp_loads_stdio_servers(tmp_path):
    cfg = tmp_path / "mcp.json"
    cfg.write_text(json.dumps({"servers": {
        "premiere-pro": {"command": "node", "args": ["/x/index.js"]},
        "jarvis": {"command": "evil"},          # 예약 이름 — 무시돼야 함
        "bad": "not-a-dict",
        "no-cmd": {"args": []},
    }}), encoding="utf-8")
    s = load_external_servers(cfg)
    assert list(s) == ["premiere-pro"]
    assert s["premiere-pro"] == {"type": "stdio", "command": "node",
                                 "args": ["/x/index.js"], "env": {}}


def test_external_mcp_missing_or_corrupt(tmp_path):
    assert load_external_servers(tmp_path / "nope.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{broken", encoding="utf-8")
    assert load_external_servers(bad) == {}
