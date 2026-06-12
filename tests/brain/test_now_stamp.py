"""실시간 타임스탬프 주입 — 날짜 오답(추측) 방지."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from jarvis.brain.base import now_stamp


def test_stamp_format_and_weekday():
    fixed = datetime(2026, 6, 12, 14, 5, tzinfo=ZoneInfo("Asia/Seoul"))  # 금요일
    s = now_stamp(fixed)
    assert s == "[지금: 2026-06-12(금) 14:05 KST]"


def test_stamp_uses_kst_now_by_default():
    s = now_stamp()
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    assert f"{now.year}-{now.month:02d}-{now.day:02d}" in s
