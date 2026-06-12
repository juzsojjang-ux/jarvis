"""풀음성 업그레이드 마커(~/.jarvis/voice_full.json) 로더 테스트.

핵심 보장: 마커가 유효하면 개인용 음성 env를 켜고, 없거나 깨졌으면 조용히 None
(=launcher가 torch-free 기본값으로 폴백). 사용자가 직접 준 env가 항상 우선.
"""
from __future__ import annotations

import json

from jarvis.core.voice_full import apply_voice_full, load_voice_full

POCKET_ENV = {
    "JARVIS_TTS_BACKEND": "pocket",
    "JARVIS_VC_BACKEND": "null",
    "JARVIS_POCKET_PYTHON": "/home/u/.jarvis/voice-full/venv-pocket/bin/python",
    "JARVIS_POCKET_REF_PATH": "/home/u/.jarvis/voice-full/models/jarvis_en_ref.wav",
}


def _write(tmp_path, payload):
    p = tmp_path / "voice_full.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_missing_marker_returns_none(tmp_path):
    assert load_voice_full(tmp_path / "nope.json") is None
    assert apply_voice_full({}, path=tmp_path / "nope.json") is False


def test_valid_marker_returns_env(tmp_path):
    vp = "/home/u/.jarvis/voice-full/venv-pocket/bin/python"
    p = _write(tmp_path, {"version": 1, "mode": "pocket",
                          "env": POCKET_ENV, "verify_paths": [vp]})
    got = load_voice_full(p, exists=lambda x: x == vp)
    assert got == POCKET_ENV


def test_verify_path_missing_invalidates(tmp_path):
    # venv가 지워졌으면(업그레이드 손상) 마커를 무효로 보고 폴백.
    p = _write(tmp_path, {"env": POCKET_ENV,
                          "verify_paths": ["/gone/python"]})
    assert load_voice_full(p, exists=lambda x: False) is None


def test_corrupt_json_returns_none(tmp_path):
    p = tmp_path / "voice_full.json"
    p.write_text("{not json", encoding="utf-8")
    assert load_voice_full(p) is None


def test_empty_env_returns_none(tmp_path):
    p = _write(tmp_path, {"env": {}, "verify_paths": []})
    assert load_voice_full(p) is None


def test_apply_setdefault_user_env_wins(tmp_path):
    vp = "/v/python"
    p = _write(tmp_path, {"env": {"JARVIS_TTS_BACKEND": "pocket",
                                  "JARVIS_VC_BACKEND": "null"},
                          "verify_paths": [vp]})
    environ = {"JARVIS_TTS_BACKEND": "edge"}  # 사용자가 직접 지정
    applied = apply_voice_full(environ, path=p, exists=lambda x: True)
    assert applied is True
    assert environ["JARVIS_TTS_BACKEND"] == "edge"      # 사용자 값 보존
    assert environ["JARVIS_VC_BACKEND"] == "null"       # 마커 값 주입


def test_apply_no_marker_does_nothing(tmp_path):
    environ = {}
    assert apply_voice_full(environ, path=tmp_path / "x.json") is False
    assert environ == {}


def test_non_string_env_value_coerced(tmp_path):
    vp = "/v/python"
    p = _write(tmp_path, {"env": {"JARVIS_RVC_F0_UP": -12}, "verify_paths": [vp]})
    got = load_voice_full(p, exists=lambda x: True)
    assert got == {"JARVIS_RVC_F0_UP": "-12"}
