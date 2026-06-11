"""tests/setup/test_server.py — SetupServer 단위 테스트.

실제 API 호출, 실제 keyring, 실제 ~/.jarvis 파일을 절대 건드리지 않는다.
validator 와 store_save 는 모두 주입한다.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from jarvis.setup.server import SetupServer


# ---------------------------------------------------------------------------
# 공용 헬퍼
# ---------------------------------------------------------------------------

def _get(port: int, path: str = "/"):
    url = f"http://127.0.0.1:{port}{path}"
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.read().decode("utf-8")


def _post_setup(port: int, provider: str, key: str = ""):
    payload = json.dumps({"provider": provider, "key": key}).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/setup",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


async def _always_ok(provider, key):
    return True, "ok"


async def _always_fail(provider, key):
    return False, "bad"


def _noop_store(provider, key):
    pass


# ---------------------------------------------------------------------------
# 픽스처
# ---------------------------------------------------------------------------

@pytest.fixture()
def server():
    """기본 서버: validator = 항상 성공, store_save = noop."""
    srv = SetupServer(
        host="127.0.0.1",
        port=0,
        validator=_always_ok,
        store_save=_noop_store,
    )
    srv.start()
    yield srv
    srv.stop()


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------

def test_get_root_returns_200(server):
    status, html = _get(server.port, "/")
    assert status == 200


def test_get_root_contains_providers(server):
    _status, html = _get(server.port, "/")
    assert "Claude" in html
    assert "Gemini" in html
    assert "GPT" in html


def test_get_root_contains_korean(server):
    _status, html = _get(server.port, "/")
    assert "자비스" in html or "시작" in html


def test_get_root_contains_key_input(server):
    """페이지에 API 키 입력칸이 있어야 한다."""
    _status, html = _get(server.port, "/")
    assert "keyInput" in html or "API 키" in html


def test_get_unknown_path_404(server):
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(server.port, "/unknown")
    assert exc.value.code == 404


# ---------------------------------------------------------------------------
# POST /setup — 성공(claude)
# ---------------------------------------------------------------------------

def test_post_claude_success(server):
    status, body = _post_setup(server.port, "claude")
    assert status == 200
    assert body["ok"] is True


def test_post_claude_sets_done_and_chosen(server):
    _post_setup(server.port, "claude")
    assert server.done.is_set()
    assert server.chosen == "claude"


def test_post_claude_calls_store_save():
    calls: list[tuple[str, str]] = []

    def recording_store(provider, key):
        calls.append((provider, key))

    srv = SetupServer(
        host="127.0.0.1", port=0, validator=_always_ok, store_save=recording_store
    )
    srv.start()
    try:
        _post_setup(srv.port, "claude")
        assert calls == [("claude", "")]
    finally:
        srv.stop()


# ---------------------------------------------------------------------------
# POST /setup — 실패(bad validator)
# ---------------------------------------------------------------------------

def test_post_bad_key_returns_ok_false():
    srv = SetupServer(
        host="127.0.0.1", port=0, validator=_always_fail, store_save=_noop_store
    )
    srv.start()
    try:
        status, body = _post_setup(srv.port, "gemini", key="bad-key")
        assert status == 200
        assert body["ok"] is False
        assert "error" in body
    finally:
        srv.stop()


def test_post_bad_key_does_not_call_store_save():
    calls: list = []

    def recording_store(provider, key):
        calls.append((provider, key))

    srv = SetupServer(
        host="127.0.0.1", port=0, validator=_always_fail, store_save=recording_store
    )
    srv.start()
    try:
        _post_setup(srv.port, "gemini", key="bad-key")
        assert calls == []
    finally:
        srv.stop()


def test_post_bad_key_done_not_set():
    srv = SetupServer(
        host="127.0.0.1", port=0, validator=_always_fail, store_save=_noop_store
    )
    srv.start()
    try:
        _post_setup(srv.port, "gemini", key="bad")
        assert not srv.done.is_set()
    finally:
        srv.stop()


# ---------------------------------------------------------------------------
# POST /setup — 잘못된 provider
# ---------------------------------------------------------------------------

def test_post_empty_provider_fails(server):
    """빈 provider는 400 또는 ok=False 응답을 반환해야 한다."""
    try:
        status, body = _post_setup(server.port, "")
        # 200 ok=False 경로
        assert body.get("ok") is False
    except urllib.error.HTTPError as e:
        # 400 경로도 허용
        assert e.code == 400


# ---------------------------------------------------------------------------
# url 속성
# ---------------------------------------------------------------------------

def test_url_includes_port(server):
    assert str(server.port) in server.url
    assert server.url.startswith("http://127.0.0.1:")
