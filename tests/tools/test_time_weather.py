import asyncio
import re

import jarvis.tools.builtin.time_weather as tw
from jarvis.tools.builtin.time_weather import get_time, get_weather


def test_get_time_returns_korean_kst_string():
    out = asyncio.run(get_time.call({}))
    assert re.match(
        r"\d{4}년 \d{1,2}월 \d{1,2}일 [월화수목금토일]요일 \d{1,2}시 \d{1,2}분입니다\.",
        out,
    )


def test_get_weather_formats_korean_offline(monkeypatch):
    async def fake_fetch(latitude, longitude):
        assert (round(latitude, 3), round(longitude, 3)) == (35.180, 129.076)
        return {"temperature_2m": 21.4, "weather_code": 61}

    monkeypatch.setattr(tw, "_fetch_current", fake_fetch)
    out = asyncio.run(get_weather.call({"city": "부산"}))
    assert "부산" in out
    assert "약한 비" in out
    assert "21.4" in out


def test_get_weather_defaults_to_seoul(monkeypatch):
    async def fake_fetch(latitude, longitude):
        assert round(latitude, 3) == 37.566
        return {"temperature_2m": 3.0, "weather_code": 0}

    monkeypatch.setattr(tw, "_fetch_current", fake_fetch)
    out = asyncio.run(get_weather.call({}))
    assert "서울" in out and "맑음" in out
