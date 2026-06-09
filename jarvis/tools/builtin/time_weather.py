from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from anthropic import beta_async_tool

_CITY_COORDS: dict[str, tuple[float, float]] = {
    "서울": (37.5665, 126.9780),
    "부산": (35.1796, 129.0756),
    "인천": (37.4563, 126.7052),
    "대구": (35.8714, 128.6014),
    "대전": (36.3504, 127.3845),
    "광주": (35.1595, 126.8526),
}

_WMO: dict[int, str] = {
    0: "맑음", 1: "대체로 맑음", 2: "구름 조금", 3: "흐림",
    45: "안개", 48: "서리 안개",
    51: "약한 이슬비", 53: "이슬비", 55: "강한 이슬비",
    61: "약한 비", 63: "비", 65: "강한 비",
    71: "약한 눈", 73: "눈", 75: "강한 눈",
    80: "소나기", 81: "강한 소나기", 95: "천둥번개",
}


async def _fetch_current(latitude: float, longitude: float) -> dict:
    """Fetch Open-Meteo current weather (no API key). Patched out in tests."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": latitude,
                "longitude": longitude,
                "current": "temperature_2m,weather_code",
                "timezone": "auto",
            },
        )
        resp.raise_for_status()
        return resp.json()["current"]


@beta_async_tool
async def get_time() -> str:
    """현재 한국 표준시(KST)의 날짜와 시간을 조회합니다."""
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    days = ["월", "화", "수", "목", "금", "토", "일"]
    return (
        f"{now.year}년 {now.month}월 {now.day}일 "
        f"{days[now.weekday()]}요일 {now.hour}시 {now.minute}분입니다."
    )


@beta_async_tool
async def get_weather(city: str = "서울") -> str:
    """한국 도시의 현재 날씨를 조회합니다.

    Args:
        city: 날씨를 조회할 한국 도시 이름 (예: 서울, 부산). 기본값은 서울입니다.
    """
    latitude, longitude = _CITY_COORDS.get(city, _CITY_COORDS["서울"])
    current = await _fetch_current(latitude, longitude)
    desc = _WMO.get(int(current.get("weather_code", 0)), "알 수 없음")
    temp = current.get("temperature_2m")
    return f"{city}의 현재 날씨는 {desc}, 기온은 섭씨 {temp}도입니다."
