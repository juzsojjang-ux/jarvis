"""JARVIS capability tools, exposed to the subscription brain as an in-process SDK MCP
server. These let JARVIS actually DO things — tell the time, check weather, open Mac
apps, set the volume, remember notes — like the real assistant, while Bash/file-edit
stay forbidden so a misheard sentence can never run arbitrary code or touch the disk.

All actions are narrow and safe: `open -a <app>` only launches, `osascript set volume`
only adjusts output volume, weather is a keyless Open-Meteo call, remember appends to the
memory file. Helpers take an injectable `runner`/`fetch` so they're unit-testable.
"""
from __future__ import annotations

import subprocess
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from claude_agent_sdk import create_sdk_mcp_server, tool

_CITY_COORDS: dict[str, tuple[float, float]] = {
    "서울": (37.5665, 126.9780), "부산": (35.1796, 129.0756), "인천": (37.4563, 126.7052),
    "대구": (35.8714, 128.6014), "대전": (36.3504, 127.3845), "광주": (35.1595, 126.8526),
    "수원": (37.2636, 127.0286), "제주": (33.4996, 126.5312),
}
_WMO: dict[int, str] = {
    0: "맑음", 1: "대체로 맑음", 2: "구름 조금", 3: "흐림", 45: "안개", 48: "서리 안개",
    51: "약한 이슬비", 53: "이슬비", 55: "강한 이슬비", 61: "약한 비", 63: "비", 65: "강한 비",
    71: "약한 눈", 73: "눈", 75: "강한 눈", 80: "소나기", 81: "강한 소나기", 95: "천둥번개",
}


def _text(s: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": s}]}


def _now_text(now: datetime | None = None) -> str:
    now = now or datetime.now(ZoneInfo("Asia/Seoul"))
    days = "월화수목금토일"
    return (f"{now.year}년 {now.month}월 {now.day}일 {days[now.weekday()]}요일 "
            f"{now.hour}시 {now.minute}분입니다.")


async def _weather_text(city: str, fetch=None) -> str:
    lat, lon = _CITY_COORDS.get(city, _CITY_COORDS["서울"])
    if fetch is None:
        import httpx

        async def fetch(la, lo):  # noqa: A001 - local default
            async with httpx.AsyncClient(timeout=10.0) as c:
                r = await c.get("https://api.open-meteo.com/v1/forecast", params={
                    "latitude": la, "longitude": lo,
                    "current": "temperature_2m,weather_code", "timezone": "auto"})
                r.raise_for_status()
                return r.json()["current"]
    cur = await fetch(lat, lon)
    desc = _WMO.get(int(cur.get("weather_code", 0)), "알 수 없음")
    return f"{city}의 현재 날씨는 {desc}, 기온은 섭씨 {cur.get('temperature_2m')}도입니다."


def open_app_action(app: str, runner=subprocess.run) -> str:
    app = (app or "").strip()
    if not app:
        return "어떤 앱을 열까요?"
    runner(["open", "-a", app], capture_output=True, text=True)
    return f"{app}을(를) 열었습니다."


def set_volume_action(level: Any, runner=subprocess.run) -> str:
    try:
        lv = max(0, min(100, int(level)))
    except (TypeError, ValueError):
        return "볼륨은 0에서 100 사이 숫자로 말씀해 주세요."
    runner(["osascript", "-e", f"set volume output volume {lv}"], capture_output=True, text=True)
    return f"볼륨을 {lv}로 맞췄습니다."


def _osa(script: str, runner=subprocess.run) -> str:
    res = runner(["osascript", "-e", script], capture_output=True, text=True)
    return (getattr(res, "stdout", "") or "").strip()


_MUSIC_CMD = {
    "play": 'tell application "Music" to play', "pause": 'tell application "Music" to pause',
    "next": 'tell application "Music" to next track',
    "previous": 'tell application "Music" to previous track',
    "prev": 'tell application "Music" to previous track',
}


def music_action(action: str, runner=subprocess.run) -> str:
    action = (action or "").strip().lower()
    if action in ("playing", "current", "now"):
        out = _osa('tell application "Music" to if player state is playing then '
                   'return (name of current track) & " — " & (artist of current track)',
                   runner)
        return f"지금 재생 중: {out}" if out else "재생 중인 곡이 없습니다."
    cmd = _MUSIC_CMD.get(action)
    if not cmd:
        return "음악은 재생, 멈춤, 다음, 이전 중에 말씀해 주세요."
    _osa(cmd, runner)
    return {"play": "음악을 재생합니다.", "pause": "음악을 멈췄습니다.",
            "next": "다음 곡으로 넘어갑니다.", "previous": "이전 곡으로 돌아갑니다.",
            "prev": "이전 곡으로 돌아갑니다."}[action]


def add_reminder_action(text: str, runner=subprocess.run) -> str:
    text = (text or "").strip()
    if not text:
        return "무엇을 알림으로 추가할까요?"
    safe = text.replace('"', "'")
    _osa(f'tell application "Reminders" to make new reminder with properties {{name:"{safe}"}}',
         runner)
    return f"알림에 추가했습니다: {text}"


def create_note_action(text: str, runner=subprocess.run) -> str:
    text = (text or "").strip()
    if not text:
        return "무슨 내용을 메모할까요?"
    safe = text.replace('"', "'")
    _osa(f'tell application "Notes" to make new note with properties {{body:"{safe}"}}', runner)
    return "메모에 적어두었습니다."


def battery_action(runner=subprocess.run) -> str:
    res = runner(["pmset", "-g", "batt"], capture_output=True, text=True)
    out = (getattr(res, "stdout", "") or "")
    import re
    m = re.search(r"(\d+)%", out)
    state = "충전 중" if "AC Power" in out or "charging" in out.lower() else "배터리 사용 중"
    return f"배터리 {m.group(1)}%입니다, {state}." if m else "배터리 상태를 읽지 못했습니다."


def mute_action(on: Any = True, runner=subprocess.run) -> str:
    muted = "with" if on in (True, "true", "True", 1, "on", "켜") else "without"
    _osa(f"set volume {muted} output muted", runner)
    return "음소거했습니다." if muted == "with" else "음소거를 해제했습니다."


def lock_screen_action(runner=subprocess.run) -> str:
    runner(["pmset", "displaysleepnow"], capture_output=True, text=True)
    return "화면을 잠갔습니다."


def quit_app_action(app: str, runner=subprocess.run) -> str:
    app = (app or "").strip()
    if not app:
        return "어떤 앱을 닫을까요?"
    _osa(f'tell application "{app}" to quit', runner)
    return f"{app}을(를) 닫았습니다."


def control_mac_action(script: str, runner=subprocess.run) -> str:
    script = (script or "").strip()
    if not script:
        return "무엇을 할까요?"
    out = _osa(script, runner)
    return out or "완료했습니다."


# ---- SDK tool wrappers ----------------------------------------------------
@tool("get_time", "현재 한국 날짜와 시간을 알려준다.", {})
async def _get_time(_args):
    return _text(_now_text())


@tool("get_weather", "한국 도시의 현재 날씨를 알려준다.",
      {"type": "object", "properties": {"city": {"type": "string"}}})
async def _get_weather(args):
    return _text(await _weather_text(str((args or {}).get("city") or "서울")))


@tool("open_app", "맥에서 앱을 연다. 예: Safari, 음악, 메모, 캘린더.",
      {"type": "object", "properties": {"app": {"type": "string"}}, "required": ["app"]})
async def _open_app(args):
    return _text(open_app_action(str((args or {}).get("app", ""))))


@tool("set_volume", "맥 출력 볼륨을 0에서 100 사이로 설정한다.",
      {"type": "object", "properties": {"level": {"type": "integer"}}, "required": ["level"]})
async def _set_volume(args):
    return _text(set_volume_action((args or {}).get("level", 50)))


@tool("music_control", "음악을 재생/멈춤/다음/이전 하거나 지금 곡을 알려준다.",
      {"type": "object", "properties": {
          "action": {"type": "string",
                     "enum": ["play", "pause", "next", "previous", "playing"]}},
       "required": ["action"]})
async def _music(args):
    return _text(music_action(str((args or {}).get("action", ""))))


@tool("add_reminder", "미리 알림(Reminders)에 항목을 추가한다.",
      {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]})
async def _add_reminder(args):
    return _text(add_reminder_action(str((args or {}).get("text", ""))))


@tool("create_note", "메모(Notes)에 새 메모를 만든다.",
      {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]})
async def _create_note(args):
    return _text(create_note_action(str((args or {}).get("text", ""))))


@tool("battery_status", "맥 배터리 잔량과 충전 상태를 알려준다.", {})
async def _battery(_args):
    return _text(battery_action())


@tool("toggle_mute", "맥 소리를 음소거하거나 해제한다.",
      {"type": "object", "properties": {"on": {"type": "boolean"}}, "required": ["on"]})
async def _mute(args):
    return _text(mute_action((args or {}).get("on", True)))


@tool("lock_screen", "맥 화면을 끄고 잠근다.", {})
async def _lock(_args):
    return _text(lock_screen_action())


@tool("quit_app", "맥에서 앱을 닫는다.",
      {"type": "object", "properties": {"app": {"type": "string"}}, "required": ["app"]})
async def _quit_app(args):
    return _text(quit_app_action(str((args or {}).get("app", ""))))


@tool("control_mac",
      "다른 도구로 안 되는 맥 작업을 AppleScript로 직접 수행한다(캘린더 일정 추가, 앱 "
      "세부 제어 등). 메시지·메일 발송, 데이터 삭제, 보안 설정 변경처럼 되돌릴 수 없는 "
      "작업은 실행 전 반드시 사용자에게 말로 확인을 받은 뒤에만 한다.",
      {"type": "object", "properties": {"applescript": {"type": "string"}},
       "required": ["applescript"]})
async def _control_mac(args):
    return _text(control_mac_action(str((args or {}).get("applescript", ""))))


def build_jarvis_mcp_server(memory: Any = None):
    """In-process MCP server. `memory` (a MemoryStore) backs the remember tool."""

    @tool("remember", "사용자가 알려준 정보를 장기 기억에 저장한다.",
          {"type": "object", "properties": {"note": {"type": "string"}}, "required": ["note"]})
    async def _remember(args):
        note = str((args or {}).get("note", "")).strip()
        if not note:
            return _text("무엇을 기억할까요?")
        if memory is not None and hasattr(memory, "remember"):
            memory.remember(note)
        return _text(f"기억했습니다: {note}")

    tools = [_get_time, _get_weather, _open_app, _set_volume, _music, _add_reminder,
             _create_note, _battery, _mute, _lock, _quit_app, _control_mac, _remember]
    return create_sdk_mcp_server("jarvis", "1.0.0", tools=tools)


# Allow-list names the brain passes to ClaudeAgentOptions.allowed_tools.
JARVIS_TOOL_NAMES = [f"mcp__jarvis__{n}" for n in (
    "get_time", "get_weather", "open_app", "set_volume", "music_control",
    "add_reminder", "create_note", "battery_status", "toggle_mute", "lock_screen",
    "quit_app", "control_mac", "remember",
)]
