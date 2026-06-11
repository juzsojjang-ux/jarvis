"""codex_auth 단위 테스트 — 실제 ~/.codex 미접근, 네트워크 미사용."""
from __future__ import annotations

import asyncio
import base64
import json
import types as pyt
from pathlib import Path

import pytest

from jarvis.brain.codex_auth import (
    _account_id_from,
    _fields,
    get_access,
    is_codex_logged_in,
    load_codex_auth,
)


# ---------------------------------------------------------------------------
# 헬퍼: tmp 경로에 auth 파일 쓰기
# ---------------------------------------------------------------------------

def _write(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "auth.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _make_jwt(payload_data: dict) -> str:
    """서명 검증 불필요한 가짜 JWT (header.payload.sig)."""
    header = base64.urlsafe_b64encode(b'{"alg":"RS256"}').rstrip(b"=").decode()
    payload_bytes = json.dumps(payload_data).encode()
    payload = base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode()
    return f"{header}.{payload}.fakesig"


# ---------------------------------------------------------------------------
# 파싱: 평면 구조
# ---------------------------------------------------------------------------

def test_load_flat_structure(tmp_path):
    p = _write(tmp_path, {
        "access_token": "tok_flat",
        "refresh_token": "ref_flat",
        "expires": 9999999999000,
        "accountId": "acc_flat",
    })
    f = load_codex_auth(p)
    assert f is not None
    assert f["access_token"] == "tok_flat"
    assert f["refresh_token"] == "ref_flat"
    assert f["accountId"] == "acc_flat"


# ---------------------------------------------------------------------------
# 파싱: 중첩 tokens.{} 구조
# ---------------------------------------------------------------------------

def test_load_nested_tokens_structure(tmp_path):
    p = _write(tmp_path, {
        "type": "oauth",
        "tokens": {
            "access_token": "tok_nested",
            "refresh_token": "ref_nested",
            "accountId": "acc_nested",
        },
        "expires": 9999999999000,
    })
    f = load_codex_auth(p)
    assert f is not None
    assert f["access_token"] == "tok_nested"
    assert f["refresh_token"] == "ref_nested"
    assert f["accountId"] == "acc_nested"


# ---------------------------------------------------------------------------
# is_codex_logged_in
# ---------------------------------------------------------------------------

def test_is_logged_in_true(tmp_path):
    p = _write(tmp_path, {"access_token": "tok", "refresh_token": "ref"})
    assert is_codex_logged_in(p) is True


def test_is_logged_in_false_no_file(tmp_path):
    p = tmp_path / "nonexistent.json"
    assert is_codex_logged_in(p) is False


def test_is_logged_in_false_no_access_token(tmp_path):
    p = _write(tmp_path, {"refresh_token": "ref"})
    assert is_codex_logged_in(p) is False


# ---------------------------------------------------------------------------
# load_codex_auth returns None when no access_token
# ---------------------------------------------------------------------------

def test_load_returns_none_if_no_access_token(tmp_path):
    p = _write(tmp_path, {"refresh_token": "ref_only"})
    assert load_codex_auth(p) is None


def test_load_returns_none_if_file_missing(tmp_path):
    p = tmp_path / "missing.json"
    assert load_codex_auth(p) is None


# ---------------------------------------------------------------------------
# _account_id_from: accountId 필드 우선
# ---------------------------------------------------------------------------

def test_account_id_from_field():
    f = {"access_token": "tok", "accountId": "acc_direct_123"}
    assert _account_id_from(f) == "acc_direct_123"


# ---------------------------------------------------------------------------
# _account_id_from: JWT 페이로드 base64 디코드
# ---------------------------------------------------------------------------

def test_account_id_from_jwt_payload():
    jwt_tok = _make_jwt({
        "sub": "user-xyz",
        "https://api.openai.com/auth": {
            "chatgpt_account_id": "acc_jwt_456",
        },
    })
    f = {"access_token": jwt_tok}
    assert _account_id_from(f) == "acc_jwt_456"


def test_account_id_from_jwt_missing_field():
    jwt_tok = _make_jwt({"sub": "user-xyz"})
    f = {"access_token": jwt_tok}
    # No chatgpt_account_id in payload → returns ""
    assert _account_id_from(f) == ""


# ---------------------------------------------------------------------------
# get_access: 미로그인 → RuntimeError
# ---------------------------------------------------------------------------

def test_get_access_not_logged_in_raises(tmp_path):
    p = tmp_path / "nonexistent.json"
    with pytest.raises(RuntimeError, match="codex login"):
        asyncio.run(get_access(path=p))


# ---------------------------------------------------------------------------
# get_access: 만료 아님 → 기존 토큰 반환 (http 미호출)
# ---------------------------------------------------------------------------

def test_get_access_not_expired_returns_existing(tmp_path):
    far_future = 9_999_999_999_000  # ms — 년 2286
    p = _write(tmp_path, {
        "access_token": "tok_existing",
        "refresh_token": "ref_existing",
        "expires": far_future,
        "accountId": "acc_existing",
    })

    class _NeverHttp:
        async def post(self, *a, **kw):  # pragma: no cover
            raise AssertionError("http.post should NOT be called")

    tok, acct = asyncio.run(get_access(path=p, http=_NeverHttp()))
    assert tok == "tok_existing"
    assert acct == "acc_existing"


# ---------------------------------------------------------------------------
# get_access: 만료됨 → refresh 호출 → 새 토큰 반환 + 파일 갱신
# ---------------------------------------------------------------------------

class _FakeHttpResp:
    def __init__(self, data: dict):
        self._data = data

    def json(self) -> dict:
        return self._data


class _FakeHttp:
    def __init__(self, resp_data: dict):
        self._resp = resp_data
        self.called_with: list[dict] = []

    async def post(self, url: str, *, json: dict | None = None, **kw):
        self.called_with.append({"url": url, "json": json})
        return _FakeHttpResp(self._resp)


def test_get_access_expired_calls_refresh_and_updates_file(tmp_path):
    expired_ms = 1_000_000  # 아주 과거
    p = _write(tmp_path, {
        "access_token": "tok_old",
        "refresh_token": "ref_old",
        "expires": expired_ms,
        "accountId": "acc_old",
    })

    fake_http = _FakeHttp({"access_token": "tok_new", "expires_in": 3600})
    now_ms = expired_ms + 120_000  # 만료 이후

    tok, acct = asyncio.run(get_access(path=p, now_ms=now_ms, http=fake_http))

    # 새 토큰 반환
    assert tok == "tok_new"
    assert acct == "acc_old"

    # http.post 호출 확인
    assert len(fake_http.called_with) == 1
    call = fake_http.called_with[0]
    assert "oauth/token" in call["url"]
    assert call["json"]["grant_type"] == "refresh_token"
    assert call["json"]["refresh_token"] == "ref_old"

    # 파일 갱신 확인
    saved = json.loads(p.read_text(encoding="utf-8"))
    assert saved["access_token"] == "tok_new"


# ---------------------------------------------------------------------------
# get_access: refresh 실패 → 기존 토큰으로 진행 (RuntimeError 아님)
# ---------------------------------------------------------------------------

def test_get_access_refresh_fails_uses_old_token(tmp_path):
    expired_ms = 1_000_000
    p = _write(tmp_path, {
        "access_token": "tok_old_fallback",
        "refresh_token": "ref_fail",
        "expires": expired_ms,
        "accountId": "acc_fallback",
    })

    class _FailHttp:
        async def post(self, *a, **kw):
            raise OSError("network error")

    now_ms = expired_ms + 120_000
    tok, acct = asyncio.run(get_access(path=p, now_ms=now_ms, http=_FailHttp()))
    # _refresh 실패 시 기존 토큰으로 계속 진행
    assert tok == "tok_old_fallback"
    assert acct == "acc_fallback"
