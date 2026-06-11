import asyncio
from jarvis.brain.tool_policy import decide, READONLY, GUARDED


def _run(c): return asyncio.run(c)


def test_remote_allows_readonly_only():
    ok, _ = _run(decide("get_time", {}, remote_mode=True, trust_on=False, confirm=None))
    assert ok is True
    ok, why = _run(decide("open_app", {"app": "x"}, remote_mode=True, trust_on=False, confirm=None))
    assert ok is False and "원격" in why


def test_remote_blocks_send_even_with_confirm():
    async def yes(p): return True
    ok, why = _run(decide("send_message", {}, remote_mode=True, trust_on=False, confirm=yes))
    assert ok is False


def test_trust_allows_everything():
    ok, _ = _run(decide("send_mail", {"to": "a"}, remote_mode=False, trust_on=True, confirm=None))
    assert ok is True


def test_guarded_requires_confirm():
    calls = []
    async def yes(p): calls.append(p); return True
    ok, _ = _run(decide("send_message", {"recipient": "민지", "text": "곧 도착"},
                        remote_mode=False, trust_on=False, confirm=yes))
    assert ok is True and calls and "민지" in calls[0]

    async def no(p): return False
    ok, why = _run(decide("send_message", {}, remote_mode=False, trust_on=False, confirm=no))
    assert ok is False and "취소" in why


def test_guarded_no_confirm_denies():
    ok, why = _run(decide("send_mail", {"to": "a"}, remote_mode=False, trust_on=False, confirm=None))
    assert ok is False


def test_normal_action_auto_allowed():
    ok, _ = _run(decide("open_app", {"app": "Safari"}, remote_mode=False, trust_on=False, confirm=None))
    assert ok is True
