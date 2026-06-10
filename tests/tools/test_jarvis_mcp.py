import asyncio
import types
from datetime import datetime
from zoneinfo import ZoneInfo

from jarvis.tools.jarvis_mcp import (
    JARVIS_TOOL_NAMES,
    _now_text,
    _weather_text,
    build_jarvis_mcp_server,
    open_app_action,
    set_volume_action,
)


def test_now_text_format():
    s = _now_text(datetime(2026, 6, 10, 9, 5, tzinfo=ZoneInfo("Asia/Seoul")))
    assert "2026년 6월 10일" in s and "9시 5분" in s and "요일" in s


def test_weather_text_with_injected_fetch():
    async def fake_fetch(la, lo):
        return {"temperature_2m": 21.5, "weather_code": 3}
    s = asyncio.run(_weather_text("부산", fetch=fake_fetch))
    assert "부산" in s and "흐림" in s and "21.5" in s


def test_open_app_action_runs_open():
    calls = []
    out = open_app_action("Safari", runner=lambda *a, **k: calls.append(a[0]))
    assert calls == [["open", "-a", "Safari"]]
    assert "Safari" in out


def test_open_app_action_rejects_empty():
    out = open_app_action("   ", runner=lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    assert "어떤 앱" in out


def test_set_volume_clamps_and_runs():
    calls = []
    out = set_volume_action(150, runner=lambda *a, **k: calls.append(a[0]))
    assert calls[0] == ["osascript", "-e", "set volume output volume 100"]
    assert "100" in out


def test_set_volume_rejects_nonnumber():
    out = set_volume_action("크게", runner=lambda *a, **k: None)
    assert "숫자" in out


def test_build_server_and_tool_names():
    server = build_jarvis_mcp_server(memory=None)
    assert server is not None
    assert JARVIS_TOOL_NAMES[0] == "mcp__jarvis__get_time"
    assert "mcp__jarvis__open_app" in JARVIS_TOOL_NAMES
    # the expanded capability set is wired
    for n in ("music_control", "add_reminder", "create_note", "battery_status",
              "toggle_mute", "lock_screen", "quit_app", "control_mac"):
        assert f"mcp__jarvis__{n}" in JARVIS_TOOL_NAMES


def _cap(calls):
    return lambda *a, **k: (calls.append(a[0]) or types.SimpleNamespace(stdout=""))


def test_music_control_actions():
    from jarvis.tools.jarvis_mcp import music_action
    calls = []
    assert "재생" in music_action("play", runner=_cap(calls))
    assert calls[0] == ["osascript", "-e", 'tell application "Music" to play']
    assert "다음" in music_action("next", runner=_cap([]))
    assert "말씀해" in music_action("zzz", runner=_cap([]))  # invalid -> help text


def test_music_whats_playing_reads_stdout():
    from jarvis.tools.jarvis_mcp import music_action
    runner = lambda *a, **k: types.SimpleNamespace(stdout="좋은날 — IU\n")  # noqa: E731
    assert "좋은날" in music_action("playing", runner=runner)


def test_reminder_and_note_and_quit():
    from jarvis.tools.jarvis_mcp import (
        add_reminder_action,
        create_note_action,
        quit_app_action,
    )
    assert "추가" in add_reminder_action("우유 사기", runner=_cap([]))
    assert "메모" in create_note_action("아이디어", runner=_cap([]))
    assert "닫" in quit_app_action("Safari", runner=_cap([]))
    assert "무엇" in add_reminder_action("", runner=_cap([]))


def test_battery_and_mute_and_control():
    from jarvis.tools.jarvis_mcp import battery_action, control_mac_action, mute_action
    bat = lambda *a, **k: types.SimpleNamespace(  # noqa: E731
        stdout="Now drawing from 'Battery Power'\n -InternalBattery 77%; discharging")
    assert "77%" in battery_action(runner=bat)
    assert "음소거" in mute_action(True, runner=_cap([]))
    assert control_mac_action("", runner=_cap([])) == "무엇을 할까요?"
