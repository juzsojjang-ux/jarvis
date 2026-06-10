from jarvis.proactive.events import Announcement


def test_expiry():
    a = Announcement(kind="briefing", prompt="브리핑", priority=2,
                     created_at=100.0, expires_at=200.0)
    assert not a.expired(150.0)
    assert a.expired(200.0)


def test_fields_round_trip():
    a = Announcement(kind="battery_low", prompt="배터리 18%", priority=2,
                     created_at=0.0, expires_at=600.0)
    assert a.kind == "battery_low" and a.priority == 2 and "18" in a.prompt
