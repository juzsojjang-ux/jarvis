"""능동 알림 감시자들. 각 poll()은 '전이가 일어난 순간'에만 Announcement를
돌려준다(반복 스팸 금지). 외부 접근(subprocess/AppleScript/Quartz)은 전부 주입형 —
엔진이 to_thread에서 부르므로 여기선 동기로 단순하게 쓴다."""
from __future__ import annotations

import re
import subprocess
import time
from datetime import date, datetime

from .events import Announcement
from .sources import fetch_events, fetch_reminders

_FIVE_MIN = 300.0
_TEN_MIN = 600.0
_ONE_HOUR = 3600.0


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
                                        3, now, now + _FIVE_MIN))
                self._warned.clear()              # 충전 시작: 경고 카운터 리셋
            self._full_announced = False
        if on_ac and pct >= 100 and not self._full_announced:
            out.append(Announcement("charge_full", "배터리 완충(100%)", 3, now, now + _TEN_MIN))
            self._full_announced = True
        # 첫 폴링은 prev를 101로 간주 — 이미 임계치 아래로 부팅한 경우에도
        # 해당 문턱 경고가 즉시 1회 나간다(4%로 부팅 → 영영 침묵하던 구멍).
        effective_prev = self._prev_pct if self._prev_pct is not None else 101
        if not on_ac:
            for lv in self._levels:
                if effective_prev > lv >= pct and lv not in self._warned:
                    kind = "battery_critical" if lv <= 5 else "battery_low"
                    prio = 0 if lv <= 5 else 2
                    out.append(Announcement(
                        kind, f"배터리가 {lv}% 문턱 아래로 떨어졌다(현재 {pct}%, 방전 중)", prio,
                        now, now + _TEN_MIN))
                    self._warned.add(lv)
        if not on_ac:
            self._full_announced = False
        self._prev_pct, self._prev_ac = pct, on_ac
        return out


def _screen_locked() -> bool:
    """macOS 화면 잠금 여부 — Quartz 세션 사전. 메인 venv에서 import 확인됨."""
    import Quartz  # 지연 import: 테스트는 locked_fn 주입으로 우회

    d = Quartz.CGSessionCopyCurrentDictionary()
    return bool(d and d.get("CGSSessionScreenIsLocked", 0))


class SessionMonitor:
    """잠금/해제 전이 감지. 그날 첫 해제(기동 시 이미 해제 포함)=briefing,
    이후 해제는 쿨다운 지난 경우 greet_back. 브리핑이 인사를 겸한다."""

    interval_s = 5.0

    def __init__(self, *, locked_fn=_screen_locked, clock=time.monotonic,
                 today_fn=date.today, greet_cooldown_s=4 * 3600.0,
                 briefing_expire_s=7200.0):
        self._locked_fn = locked_fn
        self._clock = clock
        self._today = today_fn
        self._greet_cooldown_s = greet_cooldown_s
        self._briefing_expire_s = briefing_expire_s
        self._prev_locked: bool | None = None
        self._briefed_on: date | None = None
        self._last_greet = -1e12

    def _briefing(self, now: float) -> Announcement:
        self._briefed_on = self._today()
        return Announcement(
            "briefing",
            "오늘의 아침 브리핑을 하라 — get_weather, get_reminders, "
            "get_calendar_events 도구로 날씨·미리알림·오늘 일정을 모아 짧게 보고",
            2, now, now + self._briefing_expire_s)

    def poll(self) -> list[Announcement]:
        locked = bool(self._locked_fn())
        now = self._clock()
        out: list[Announcement] = []
        first = self._prev_locked is None
        unlocked_now = (self._prev_locked is True and not locked)
        if (first and not locked) or unlocked_now:
            if self._briefed_on != self._today():
                out.append(self._briefing(now))
                self._last_greet = now             # 브리핑이 인사를 겸한다
            elif unlocked_now and now - self._last_greet >= self._greet_cooldown_s:
                out.append(Announcement("greet_back", "주인님이 자리로 돌아왔다 — 짧게 맞이하라",
                                        4, now, now + _FIVE_MIN))
                self._last_greet = now
        self._prev_locked = locked
        return out


class LateNightMonitor:
    """02~05시 사이에 화면이 깨어 있으면 하루 1회, 영화처럼 한마디."""

    interval_s = 300.0

    def __init__(self, *, locked_fn=_screen_locked, clock=time.monotonic,
                 now_fn=datetime.now, today_fn=date.today):
        self._locked_fn = locked_fn
        self._clock = clock
        self._now = now_fn
        self._today = today_fn
        self._nudged_on: date | None = None

    def poll(self) -> list[Announcement]:
        if self._nudged_on == self._today():
            return []
        if self._locked_fn():
            return []
        if not (2 <= self._now().hour < 5):
            return []
        self._nudged_on = self._today()
        now = self._clock()
        return [Announcement("late_night",
                             "새벽 2시가 넘었는데 주인님이 아직 깨어 있다 — 정중하지만 "
                             "위트 있게 취침을 권하라", 4, now, now + _ONE_HOUR)]


class _DueMonitor:
    """임박 항목 감시 공통: fetch가 (id, 제목, 남은초)를 주면 lead 이내 항목을
    id당 1회 알린다. 항목이 사라지면 셋에서 정리해, 같은 id가 새 due로
    재등장하면 다시 알릴 수 있다."""

    interval_s = 60.0

    def __init__(self, *, kind: str, what: str, lead_s: float, fetch,
                 clock=time.monotonic):
        self._kind = kind
        self._what = what
        self._lead_s = lead_s
        self._fetch = fetch
        self._clock = clock
        self._announced: set[str] = set()

    def poll(self) -> list[Announcement]:
        items = self._fetch(int(self._lead_s * 2))
        now = self._clock()
        live_ids = {i for i, _, _ in items}
        self._announced &= live_ids               # 사라진 항목은 셋에서 정리
        out: list[Announcement] = []
        for ident, title, secs in items:
            if secs <= self._lead_s and ident not in self._announced:
                mins = max(1, secs // 60)
                out.append(Announcement(
                    self._kind, f"{mins}분 뒤 {self._what}: {title}", 1,
                    now, now + secs))
                self._announced.add(ident)
        return out


class RemindersMonitor(_DueMonitor):
    def __init__(self, *, lead_s: float, fetch=fetch_reminders, clock=time.monotonic):
        super().__init__(kind="reminder_due", what="미리알림", lead_s=lead_s,
                         fetch=fetch, clock=clock)


class CalendarMonitor(_DueMonitor):
    interval_s = 300.0

    def __init__(self, *, lead_s: float, fetch=fetch_events, clock=time.monotonic):
        super().__init__(kind="event_soon", what="일정 시작", lead_s=lead_s,
                         fetch=fetch, clock=clock)


def build_monitors(settings) -> list:
    """설정으로 감시자 세트를 조립한다(엔진/배선에서 호출)."""
    mons: list = [
        BatteryMonitor(levels=settings.battery_warn_levels),
        SessionMonitor(greet_cooldown_s=settings.greet_cooldown_h * 3600,
                       briefing_expire_s=settings.briefing_expire_h * 3600),
        RemindersMonitor(lead_s=settings.reminder_lead_min * 60),
        CalendarMonitor(lead_s=settings.event_lead_min * 60),
    ]
    if settings.proactive_late_night:
        mons.append(LateNightMonitor())
    return mons
