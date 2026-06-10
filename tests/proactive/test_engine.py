import asyncio

from jarvis.proactive.engine import ProactiveEngine
from jarvis.proactive.events import Announcement


class _Mon:
    interval_s = 0.01

    def __init__(self, batches):
        self._batches = list(batches)

    def poll(self):
        return self._batches.pop(0) if self._batches else []


def _ann(kind, prio, t, ttl=100.0, prompt=None):
    return Announcement(kind, prompt or kind, prio, t, t + ttl)


def _engine(monitors, *, can_speak=lambda: True, cooldown_s=0.0):
    spoken = []
    t = {"v": 0.0}

    async def announce(prompt):
        spoken.append(prompt)

    eng = ProactiveEngine(monitors, announce=announce, can_speak=can_speak,
                          clock=lambda: t["v"], cooldown_s=cooldown_s, tick_s=0.01)
    return eng, spoken, t


def _run(eng, seconds=0.15):
    async def go():
        eng.start()
        await asyncio.sleep(seconds)
        eng.stop()

    asyncio.run(go())


def test_delivers_when_idle():
    eng, spoken, t = _engine([_Mon([[_ann("briefing", 2, 0.0)]])])
    _run(eng)
    assert spoken == ["briefing"]


def test_holds_while_busy_then_delivers():
    busy = {"v": True}
    eng, spoken, t = _engine([_Mon([[_ann("battery_low", 2, 0.0)]])],
                             can_speak=lambda: not busy["v"])

    async def go():
        eng.start()
        await asyncio.sleep(0.05)
        assert spoken == []          # 대화 중 보류
        busy["v"] = False
        await asyncio.sleep(0.05)
        eng.stop()

    asyncio.run(go())
    assert spoken == ["battery_low"]


def test_priority_order_and_expiry():
    anns = [_ann("greet_back", 4, 0.0), _ann("battery_critical", 0, 0.0),
            _ann("briefing", 2, 0.0, ttl=-1.0)]   # 브리핑은 이미 만료
    eng, spoken, t = _engine([_Mon([anns])])
    _run(eng)
    assert spoken[0] == "battery_critical"
    assert "briefing" not in spoken               # 만료 폐기


def test_kind_cooldown():
    eng, spoken, t = _engine(
        [_Mon([[_ann("battery_low", 2, 0.0)], [], [_ann("battery_low", 2, 0.0)]])],
        cooldown_s=999.0)
    _run(eng)
    assert spoken == ["battery_low"]              # 같은 kind 쿨다운


def test_duplicate_pending_kind_dropped():
    eng, spoken, t = _engine([_Mon([[_ann("greet_back", 4, 0.0, prompt="첫번째")]])],
                             can_speak=lambda: False)
    eng.enqueue(_ann("greet_back", 4, 0.0, prompt="두번째"))

    async def go():
        eng.start()
        await asyncio.sleep(0.05)
        eng.stop()
        assert len([a for a in eng._pending if a.kind == "greet_back"]) == 1

    asyncio.run(go())


def test_briefing_supersedes_boot_greet():
    eng, spoken, t = _engine([_Mon([[_ann("briefing", 2, 0.0)]])])
    eng.enqueue(_ann("boot_greet", 3, 0.0))
    _run(eng)
    assert "boot_greet" not in spoken and "briefing" in spoken


def test_monitor_error_does_not_kill_engine():
    class _Boom:
        interval_s = 0.01

        def poll(self):
            raise RuntimeError("monitor bug")

    eng, spoken, t = _engine([_Boom(), _Mon([[_ann("greet_back", 4, 0.0)]])])
    _run(eng)
    assert spoken == ["greet_back"]               # 죽은 감시자 무시, 엔진 생존


def test_announce_error_does_not_kill_engine():
    calls = []

    async def announce(prompt):
        calls.append(prompt)
        if len(calls) == 1:
            raise RuntimeError("brain down")

    eng = ProactiveEngine(
        [_Mon([[_ann("briefing", 2, 0.0)], [_ann("greet_back", 4, 0.0)]])],
        announce=announce, can_speak=lambda: True,
        clock=lambda: 0.0, cooldown_s=0.0, tick_s=0.01)
    _run(eng)
    assert calls == ["briefing", "greet_back"]    # 한 건 실패 후에도 다음 건 전달
