import time

from jarvis.hud.telemetry import TelemetryProvider, collect


def test_collect_clock_always_present():
    items = collect(clock="14:32", mic_on=False, task_count=0)
    ids = [i["id"] for i in items]
    assert "clock" in ids
    clock = next(i for i in items if i["id"] == "clock")
    assert clock["kind"] == "telemetry" and "14:32" in clock["title"]


def test_collect_mic_reflects_state():
    on = next(i for i in collect(clock="0", mic_on=True, task_count=0) if i["id"] == "mic")
    off = next(i for i in collect(clock="0", mic_on=False, task_count=0) if i["id"] == "mic")
    assert "●" in on["body"] or "LIVE" in on["body"]
    assert on["body"] != off["body"]


def test_collect_tasks_hidden_when_zero():
    ids = [i["id"] for i in collect(clock="0", mic_on=False, task_count=0)]
    assert "tasks" not in ids
    ids2 = [i["id"] for i in collect(clock="0", mic_on=False, task_count=3)]
    assert "tasks" in ids2


def test_collect_omits_cpu_when_none():
    ids = [i["id"] for i in collect(clock="0", mic_on=False, task_count=0, cpu=None, mem=None)]
    assert "sys" not in ids
    items = collect(clock="0", mic_on=False, task_count=0, cpu=12, mem=41)
    sysp = next(i for i in items if i["id"] == "sys")
    assert sysp["gauge"] == {"cpu": 12, "mem": 41}


def test_collect_net_optional():
    ids = [i["id"] for i in collect(clock="0", mic_on=False, task_count=0, net=None)]
    assert "net" not in ids
    ids2 = [i["id"] for i in collect(clock="0", mic_on=False, task_count=0, net=True)]
    assert "net" in ids2


def test_provider_pushes_to_hub():
    from jarvis.hud.orb_server import OrbHub
    hub = OrbHub()
    prov = TelemetryProvider(hub, state_fn=lambda: {"mic_on": True, "task_count": 2},
                             interval=0.05, clock_fn=lambda: "09:00")
    prov.start()
    time.sleep(0.15)
    prov.stop()
    evt = hub.publish("idle", 0.0)
    ids = [p["id"] for p in evt["panels"] if p["kind"] == "telemetry"]
    assert "clock" in ids and "mic" in ids and "tasks" in ids
