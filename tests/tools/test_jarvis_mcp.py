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


def test_reminders_text_lists_upcoming():
    from jarvis.tools.jarvis_mcp import reminders_text
    items = [("id-1", "회의 자료 제출", 540), ("id-2", "약 먹기", 7200)]
    out = reminders_text(fetch=lambda w, runner=None: items)
    assert "회의 자료 제출" in out and "약 먹기" in out and "9분" in out


def test_reminders_text_empty():
    from jarvis.tools.jarvis_mcp import reminders_text
    assert "없" in reminders_text(fetch=lambda w, runner=None: [])


def test_reminders_text_bad_hours_falls_back():
    from jarvis.tools.jarvis_mcp import reminders_text
    out = reminders_text(hours="이상한값", fetch=lambda w, runner=None: [])
    assert "24시간" in out


def test_calendar_text_lists_events():
    from jarvis.tools.jarvis_mcp import calendar_text
    out = calendar_text(fetch=lambda w, runner=None: [("u1", "팀 미팅", 1800)])
    assert "팀 미팅" in out and "30분" in out


def test_calendar_text_hour_formatting():
    from jarvis.tools.jarvis_mcp import calendar_text
    out = calendar_text(fetch=lambda w, runner=None: [("u1", "저녁 약속", 5400)])
    assert "1시간 30분" in out


def test_new_tools_registered():
    from jarvis.tools.jarvis_mcp import JARVIS_TOOL_NAMES
    assert "mcp__jarvis__get_reminders" in JARVIS_TOOL_NAMES
    assert "mcp__jarvis__get_calendar_events" in JARVIS_TOOL_NAMES


def test_set_timer_action_registers_on_board():
    from jarvis.proactive.timers import TimerBoard
    from jarvis.tools.jarvis_mcp import set_timer_action
    board = TimerBoard(clock=lambda: 0.0)
    out = set_timer_action(board, minutes=5, seconds=30, label="라면")
    assert "라면" in out and "5분" in out and "30초" in out
    assert board.listing() == [("라면", 330)]


def test_set_timer_action_rejects_zero():
    from jarvis.proactive.timers import TimerBoard
    from jarvis.tools.jarvis_mcp import set_timer_action
    out = set_timer_action(TimerBoard(), minutes=0, seconds=0, label="")
    assert "몇 분" in out


def test_cancel_and_list_timer_actions():
    from jarvis.proactive.timers import TimerBoard
    from jarvis.tools.jarvis_mcp import cancel_timer_action, list_timers_action
    board = TimerBoard(clock=lambda: 0.0)
    assert "없습니다" in list_timers_action(board)
    board.add(90, "회의")
    assert "회의" in list_timers_action(board) and "1분 30초" in list_timers_action(board)
    assert "취소" in cancel_timer_action(board, "회의")


def test_timer_tools_registered():
    from jarvis.tools.jarvis_mcp import JARVIS_TOOL_NAMES
    for n in ("set_timer", "cancel_timer", "list_timers"):
        assert f"mcp__jarvis__{n}" in JARVIS_TOOL_NAMES


def _recording_runner(stdout="", returncode=0):
    from types import SimpleNamespace
    calls = []

    def runner(cmd, capture_output=True, text=True, timeout=None, input=None):
        calls.append(cmd)
        return SimpleNamespace(stdout=stdout, returncode=returncode)

    runner.calls = calls
    return runner


def test_toggle_dark_mode():
    from jarvis.tools.jarvis_mcp import system_toggle_action
    r = _recording_runner()
    out = system_toggle_action("dark_mode", "toggle", runner=r)
    assert "다크" in out
    assert any("dark mode" in " ".join(c) for c in r.calls)


def test_toggle_wifi_resolves_device():
    from jarvis.tools.jarvis_mcp import system_toggle_action
    ports = "Hardware Port: Wi-Fi\nDevice: en1\nEthernet Address: aa\n"
    r = _recording_runner(stdout=ports)
    out = system_toggle_action("wifi", "off", runner=r)
    assert "껐" in out
    assert ["networksetup", "-setairportpower", "en1", "off"] in r.calls


def test_toggle_wifi_needs_explicit_state():
    from jarvis.tools.jarvis_mcp import system_toggle_action
    out = system_toggle_action("wifi", "toggle", runner=_recording_runner())
    assert "켜기" in out or "끄기" in out


def test_toggle_bluetooth_missing_blueutil():
    from jarvis.tools.jarvis_mcp import system_toggle_action

    def no_blueutil(cmd, capture_output=True, text=True, timeout=None, input=None):
        raise FileNotFoundError("blueutil")

    out = system_toggle_action("bluetooth", "on", runner=no_blueutil)
    assert "blueutil" in out


def test_toggle_brightness_presses_key_4x():
    from jarvis.tools.jarvis_mcp import system_toggle_action
    r = _recording_runner()
    system_toggle_action("brightness_up", "on", runner=r)
    assert len([c for c in r.calls if "key code 144" in " ".join(c)]) == 4


def test_toggle_sleep_and_display_off():
    from jarvis.tools.jarvis_mcp import system_toggle_action
    r = _recording_runner()
    assert "절전" in system_toggle_action("sleep", "on", runner=r)
    assert ["pmset", "sleepnow"] in r.calls
    r2 = _recording_runner()
    assert "화면" in system_toggle_action("display_off", "on", runner=r2)
    assert ["pmset", "displaysleepnow"] in r2.calls


def test_toggle_unknown_target_lists_supported():
    from jarvis.tools.jarvis_mcp import system_toggle_action
    out = system_toggle_action("프린터", "on", runner=_recording_runner())
    assert "다크모드" in out


def test_clipboard_read_truncates():
    from jarvis.tools.jarvis_mcp import clipboard_read_action
    r = _recording_runner(stdout="x" * 5000)
    out = clipboard_read_action(runner=r)
    assert "생략" in out and len(out) < 4200
    assert ["pbpaste"] in r.calls


def test_clipboard_read_empty():
    from jarvis.tools.jarvis_mcp import clipboard_read_action
    assert "비어" in clipboard_read_action(runner=_recording_runner(stdout=""))


def test_clipboard_write_pipes_text():
    from jarvis.tools.jarvis_mcp import clipboard_write_action
    captured = {}

    def runner(cmd, capture_output=True, text=True, timeout=None, input=None):
        from types import SimpleNamespace
        captured["cmd"], captured["input"] = cmd, input
        return SimpleNamespace(stdout="", returncode=0)

    out = clipboard_write_action("안녕하세요", runner=runner)
    assert "복사" in out
    assert captured["cmd"] == ["pbcopy"] and captured["input"] == "안녕하세요"


def test_run_shortcut_success_and_failure():
    from jarvis.tools.jarvis_mcp import run_shortcut_action
    ok = _recording_runner(stdout="결과물")
    out = run_shortcut_action("퇴근", runner=ok)
    assert "퇴근" in out and "결과물" in out
    fail = _recording_runner(stdout="이름1\n이름2", returncode=1)
    out = run_shortcut_action("없는것", runner=fail)
    assert "실패" in out


def test_list_shortcuts():
    from jarvis.tools.jarvis_mcp import list_shortcuts_action
    r = _recording_runner(stdout="퇴근\n방해금지\n")
    out = list_shortcuts_action(runner=r)
    assert "2개" in out and "퇴근" in out


def test_play_music_track_success():
    from types import SimpleNamespace

    from jarvis.tools.jarvis_mcp import play_music_action
    calls = []

    def runner(cmd, capture_output=True, text=True, timeout=None, input=None):
        calls.append(cmd)
        script = cmd[-1]
        if "first track" in script:
            return SimpleNamespace(stdout="", returncode=0)
        return SimpleNamespace(stdout="Money Trees — Kendrick Lamar", returncode=0)

    out = play_music_action("머니 트리", kind="track", runner=runner)
    assert "재생" in out


def test_play_music_any_falls_through_and_fails():
    from types import SimpleNamespace

    from jarvis.tools.jarvis_mcp import play_music_action

    def runner(cmd, capture_output=True, text=True, timeout=None, input=None):
        return SimpleNamespace(stdout="", returncode=1)

    out = play_music_action("없는곡", runner=runner)
    assert "찾지 못했습니다" in out and "카탈로그" in out


def test_play_music_escapes_quotes():
    from types import SimpleNamespace

    from jarvis.tools.jarvis_mcp import play_music_action
    seen = []

    def runner(cmd, capture_output=True, text=True, timeout=None, input=None):
        seen.append(cmd[-1])
        return SimpleNamespace(stdout="", returncode=0)

    play_music_action('악"곡', kind="track", runner=runner)
    assert '\\"' in seen[0]


def test_play_music_registered():
    from jarvis.tools.jarvis_mcp import JARVIS_TOOL_NAMES
    assert "mcp__jarvis__play_music" in JARVIS_TOOL_NAMES
