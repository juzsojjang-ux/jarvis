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

    tools = [_get_time, _get_weather, _open_app, _set_volume, _remember]
    return create_sdk_mcp_server("jarvis", "1.0.0", tools=tools)


# Allow-list names the brain passes to ClaudeAgentOptions.allowed_tools.
JARVIS_TOOL_NAMES = [
    "mcp__jarvis__get_time", "mcp__jarvis__get_weather", "mcp__jarvis__open_app",
    "mcp__jarvis__set_volume", "mcp__jarvis__remember",
]
