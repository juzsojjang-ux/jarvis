import json
import urllib.error
import urllib.request

import pytest

from jarvis.remote.server import RemoteServer

TOKEN = "test-token-123"


def _post(port, text="안녕", token=TOKEN, path="/ask"):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps({"text": text}).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


@pytest.fixture()
def server():
    calls = []

    def handler(text):
        calls.append(text)
        if text == "boom":
            raise RuntimeError("brain down")
        if text == "slow":
            raise TimeoutError()
        return {"reply": f"답: {text}", "reply_en": f"re: {text}"}

    srv = RemoteServer(handler, "127.0.0.1", 0, TOKEN)
    srv.start()
    yield srv, calls
    srv.stop()


def test_ok_roundtrip(server):
    srv, calls = server
    status, body = _post(srv.port)
    assert status == 200
    assert body["reply"] == "답: 안녕"
    assert calls == ["안녕"]


def test_rejects_bad_token(server):
    srv, calls = server
    with pytest.raises(urllib.error.HTTPError) as e:
        _post(srv.port, token="wrong")
    assert e.value.code == 401
    assert calls == []  # 핸들러까지 못 간다


def test_rejects_empty_text(server):
    srv, _calls = server
    with pytest.raises(urllib.error.HTTPError) as e:
        _post(srv.port, text="  ")
    assert e.value.code == 400


def test_handler_error_is_500(server):
    srv, _calls = server
    with pytest.raises(urllib.error.HTTPError) as e:
        _post(srv.port, text="boom")
    assert e.value.code == 500


def test_handler_timeout_is_504(server):
    srv, _calls = server
    with pytest.raises(urllib.error.HTTPError) as e:
        _post(srv.port, text="slow")
    assert e.value.code == 504


def test_unknown_path_404(server):
    srv, _calls = server
    with pytest.raises(urllib.error.HTTPError) as e:
        _post(srv.port, path="/other")
    assert e.value.code == 404
