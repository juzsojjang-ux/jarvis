import json
import socket
import urllib.request

import pytest

from jarvis.hud.orb_server import OrbHub, OrbServer


# ---- hub fan-out (deterministic) -----------------------------------------
def test_subscribe_replays_current_state():
    hub = OrbHub()
    hub.publish("thinking", 0.4)
    q = hub.subscribe()
    assert q.get_nowait() == {"state": "thinking", "level": 0.4, "text": "", "notice": "", "expand": False, "panels": []}


def test_publish_fans_out_to_clients():
    hub = OrbHub()
    q = hub.subscribe()
    q.get_nowait()  # drop the replayed idle
    hub.publish("speaking", 0.7, "안녕하세요")
    assert q.get_nowait() == {"state": "speaking", "level": 0.7, "text": "안녕하세요", "notice": "", "expand": False, "panels": []}


def test_subtitle_persists_then_clears_when_not_speaking():
    hub = OrbHub()
    hub.publish("speaking", 0.5, "자막 텍스트")
    assert hub.publish("speaking", 0.6)["text"] == "자막 텍스트"   # level pump keeps it
    assert hub.publish("idle", 0.0)["text"] == ""                 # cleared off speaking


def test_attentive_state_passes_through():
    # follow-up 청취 표시 — 화이트리스트 누락으로 idle로 뭉개지면 기능이 통째로 죽는다
    hub = OrbHub()
    assert hub.publish("attentive", 0.2)["state"] == "attentive"


def test_invalid_state_and_level_are_sanitised():
    hub = OrbHub()
    evt = hub.publish("bogus", 5.0)
    assert evt["state"] == "idle" and evt["level"] == 1.0
    assert hub.publish("speaking", -3.0)["level"] == 0.0


def test_unsubscribe_stops_delivery():
    hub = OrbHub()
    q = hub.subscribe()
    hub.unsubscribe(q)
    assert hub.client_count() == 0


def test_publish_includes_expand():
    from jarvis.hud.orb_server import OrbHub
    hub = OrbHub()
    evt = hub.publish("speaking", 0.5, expand=True)
    assert evt["expand"] is True
    evt2 = hub.publish("idle", 0.0)
    assert evt2["expand"] is True   # 명시 안 하면 마지막 값 유지(sticky)
    evt3 = hub.publish("idle", 0.0, expand=False)
    assert evt3["expand"] is False


# ---- panels 모델 -----------------------------------------------------------
def test_emit_includes_panels_key_default_empty():
    hub = OrbHub()
    evt = hub.publish("idle", 0.0)
    assert evt["panels"] == []


def test_notice_becomes_single_brain_card():
    hub = OrbHub()
    evt = hub.publish_notice("검색 결과\n- 항목1\n- 항목2")
    assert len(evt["panels"]) == 1
    p = evt["panels"][0]
    assert p["kind"] == "brain" and p["title"] == "검색 결과"
    assert "항목1" in p["body"]
    assert evt["notice"] == "검색 결과\n- 항목1\n- 항목2"  # 하위호환 유지


def test_notice_splits_into_cards_on_separator():
    hub = OrbHub()
    evt = hub.publish_notice("일정\n3시 회의\n---\n검색\n뉴스 5건")
    titles = [p["title"] for p in evt["panels"] if p["kind"] == "brain"]
    assert titles == ["일정", "검색"]


def test_warn_card_tone():
    hub = OrbHub()
    evt = hub.publish_notice("⚠ 오류\n디스크 부족")
    assert evt["panels"][0]["tone"] == "warn"


def test_publish_telemetry_merges_with_brain():
    hub = OrbHub()
    hub.publish_notice("메인\n본문")
    evt = hub.publish_telemetry([
        {"id": "clock", "title": "14:32", "body": "", "kind": "telemetry", "tone": "cyan"},
    ])
    kinds = [p["kind"] for p in evt["panels"]]
    assert kinds.count("brain") == 1 and kinds.count("telemetry") == 1


def test_telemetry_replaced_not_appended():
    hub = OrbHub()
    hub.publish_telemetry([{"id": "a", "title": "A", "body": "", "kind": "telemetry", "tone": "cyan"}])
    evt = hub.publish_telemetry([{"id": "b", "title": "B", "body": "", "kind": "telemetry", "tone": "cyan"}])
    tel = [p for p in evt["panels"] if p["kind"] == "telemetry"]
    assert len(tel) == 1 and tel[0]["id"] == "b"


# ---- live HTTP server -----------------------------------------------------
@pytest.fixture
def server():
    s = OrbServer(port=0)
    s.start()
    yield s
    s.stop()


def test_serves_orb_html(server):
    body = urllib.request.urlopen(server.url, timeout=3).read().decode("utf-8")
    assert "JARVIS" in body and "<canvas" in body  # Canvas2D HUD
    assert "EventSource" in body and "/events" in body


def test_health_endpoint(server):
    body = urllib.request.urlopen(server.url + "health", timeout=3).read()
    assert body == b"ok"


def test_sse_streams_published_events(server):
    # raw socket so we can read the unbounded event-stream with a timeout
    host, port = "127.0.0.1", server.port
    sock = socket.create_connection((host, port), timeout=3)
    sock.sendall(b"GET /events HTTP/1.1\r\nHost: x\r\n\r\n")
    sock.settimeout(3)
    first = sock.recv(4096)  # headers + replayed idle state
    assert b"text/event-stream" in first
    server.publish("speaking", 0.55)
    # read until we see the speaking event (may arrive in a later chunk)
    buf = first
    for _ in range(5):
        try:
            buf += sock.recv(4096)
        except TimeoutError:
            break
        if b'"state": "speaking"' in buf:
            break
    sock.close()
    assert b'"state": "speaking"' in buf
    payloads = [ln.strip() for ln in buf.split(b"\n") if ln.strip().startswith(b"data:")]
    assert any(json.loads(p[5:].decode())["level"] == 0.55 for p in payloads)


def test_serves_orb_asset():
    from jarvis.hud.orb_server import OrbServer
    srv = OrbServer(); srv.start()
    try:
        import urllib.request
        base = f"http://127.0.0.1:{srv.port}"
        r = urllib.request.urlopen(base + "/assets/orb.mp4")
        assert r.status == 200
        assert r.headers["Content-Type"] == "video/mp4"
        assert int(r.headers["Content-Length"]) > 100000
    finally:
        srv.stop()


def test_alpha_assets_served():
    from jarvis.hud.orb_server import OrbServer
    srv = OrbServer(port=0)
    srv.start()
    try:
        base = srv.url
        for name, ctype in [("orb-alpha.webm", "video/webm"), ("orb-alpha.mov", "video/quicktime")]:
            with urllib.request.urlopen(base + "assets/" + name, timeout=3) as r:
                assert r.status == 200
                assert r.headers["Content-Type"] == ctype
                assert int(r.headers["Content-Length"]) > 100000
    finally:
        srv.stop()


def test_assistant_name_injected_into_html(monkeypatch):
    from jarvis.hud.orb_server import _apply_assistant_name
    body = b"<h1>J.A.R.V.I.S</h1> fillText(\"J.A.R.V.I.S\")"
    monkeypatch.setenv("JARVIS_ASSISTANT_NAME", "friday")
    out = _apply_assistant_name(body)
    assert b"F.R.I.D.A.Y" in out and b"J.A.R.V.I.S" not in out
    monkeypatch.setenv("JARVIS_ASSISTANT_NAME", "맥스")
    assert "맥스".encode() in _apply_assistant_name(body)
    monkeypatch.delenv("JARVIS_ASSISTANT_NAME")
    assert _apply_assistant_name(body) == body  # 기본명은 무변경
