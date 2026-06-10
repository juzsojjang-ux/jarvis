"""능동 알림 감시자들. 각 poll()은 '전이가 일어난 순간'에만 Announcement를
돌려준다(반복 스팸 금지). subprocess는 주입형 runner — 엔진이
to_thread에서 부르므로 여기선 동기로 단순하게 쓴다."""
from __future__ import annotations

import re
import subprocess
import time

from .events import Announcement

_TEN_MIN = 600.0


class BatteryMonitor:
    """pmset -g batt 파싱. 문턱 하향 돌파/전원 전이/완충 시 각각 1회."""

    interval_s = 60.0

    def __init__(self, levels=(20, 10, 5), runner=subprocess.run,
                 clock=time.monotonic):
        self._levels = sorted(levels, reverse=True)   # [20, 10, 5]
        self._runner = runner
        self._clock = clock
        self._prev_pct: int | None = None
        self._prev_ac: bool | None = None
        self._warned: set[int] = set()
        self._full_announced = False

    def _read(self) -> tuple[int, bool] | None:
        try:
            res = self._runner(["pmset", "-g", "batt"], capture_output=True,
                               text=True, timeout=10)
            out = (getattr(res, "stdout", "") or "")
        except Exception:  # noqa: BLE001 - 이번 폴링만 건너뜀
            return None
        m = re.search(r"(\d+)%", out)
        if not m:
            return None
        return int(m.group(1)), ("AC Power" in out)

    def poll(self) -> list[Announcement]:
        read = self._read()
        if read is None:
            return []
        pct, on_ac = read
        now = self._clock()
        out: list[Announcement] = []
        if self._prev_ac is not None and on_ac != self._prev_ac:
            if on_ac:
                out.append(Announcement("charger_on", f"전원이 연결됐다 (배터리 {pct}%)",
                                        3, now, now + 300))
                self._warned.clear()              # 충전 시작: 경고 카운터 리셋
            self._full_announced = False
        if on_ac and pct >= 100 and not self._full_announced:
            out.append(Announcement("charge_full", "배터리 완충(100%)", 3, now, now + _TEN_MIN))
            self._full_announced = True
        if not on_ac and self._prev_pct is not None:
            for lv in self._levels:
                if self._prev_pct > lv >= pct and lv not in self._warned:
                    kind = "battery_critical" if lv <= 5 else "battery_low"
                    prio = 0 if lv <= 5 else 2
                    out.append(Announcement(
                        kind, f"배터리가 {pct}%까지 떨어졌다(방전 중)", prio,
                        now, now + _TEN_MIN))
                    self._warned.add(lv)
        if not on_ac:
            self._full_announced = False
        self._prev_pct, self._prev_ac = pct, on_ac
        return out
