"""능동 알림 감시자들. 각 poll()은 '전이가 일어난 순간'에만 Announcement를
돌려준다(반복 스팸 금지). 외부 접근(subprocess/AppleScript/Quartz)은 전부 주입형 —
엔진이 to_thread에서 부르므로 여기선 동기로 단순하게 쓴다."""
from __future__ import annotations

import re
import subprocess
import sys
import time
from datetime import date, datetime

from .events import Announcement
from .sources import fetch_events, fetch_reminders

_FIVE_MIN = 300.0
_TEN_MIN = 600.0
_ONE_HOUR = 3600.0

# 아침 인사/브리핑 — 영화 자비스 대사 201개 분석 기반(2026-06-16): 기동/호출 자체는
# 상태보고 트리거가 아니다. 무조건적 '날씨·일정 보고'를 금하고, 예약 브리핑일 때만
# 시간·날씨·주목 일정을 짧게. 위험·응급이 아닐 때만 절제된 위트 한 줄.
_BRIEFING_PROMPT = (
    "당신은 영화 속 자비스이며, 지금은 부팅 또는 아침 기상 시점이다. 기계적인 상태 보고"
    "(시스템 점검·센서 수치·전체 항목 나열)는 절대 하지 마라 — 켜졌다는 사실만으로는 "
    "보고할 이유가 되지 않는다. 평상시 호출이면 정중한 인사 한 마디와 '무엇을 도와드릴까요?' "
    "식의 짧은 도움 제안으로 끝내고 기다려라. 단, 예약된 아침 브리핑이라면 깨어난 사람에게 "
    "필요한 것만 — 시간, 날씨, 오늘의 주목할 일정 — 집사 어조로 짧게 전하고, 자리를 비웠다 "
    "돌아온 상황이면 그동안 일어난 '주목할 만한' 사건만 한 박자로 짚어라. 필요할 때만 "
    "get_weather·get_reminders·get_calendar_events를 쓰되 매번 전부 나열하지 말 것. 존댓말 "
    "한두 문장으로, 진단 목록이 아니라 사람을 향한 말로. 위험·응급이 아닐 때만 마지막에 "
    "절제된 위트 한 줄을 더해도 좋다."
)


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
            _BRIEFING_PROMPT,
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


class TimerMonitor:
    """TimerBoard 만기 수확 — 타이머는 초 단위 체감이라 1초 폴링."""

    interval_s = 1.0

    def __init__(self, board, clock=time.monotonic):
        self._board = board
        self._clock = clock

    def poll(self) -> list[Announcement]:
        now = self._clock()
        return [Announcement("timer_done", f"타이머 종료: {lb}", 1, now, now + 120)
                for lb in self._board.pop_due()]


def build_monitors(settings, timers=None, platform: str | None = None) -> list:
    """설정으로 감시자 세트를 조립한다(엔진/배선에서 호출).

    맥 전용 감시자(잠금화면 Quartz·미리알림/캘린더 osascript·배터리 pmset)는
    darwin에서만 — 다른 플랫폼에선 폴링마다 'No module named Quartz' 류가
    로그를 도배한다(2026-06-12 윈도우 배포에서 확인)."""
    sysname = platform if platform is not None else sys.platform
    mons: list = []
    if sysname == "darwin":
        mons += [
            BatteryMonitor(levels=settings.battery_warn_levels),
            SessionMonitor(greet_cooldown_s=settings.greet_cooldown_h * 3600,
                           briefing_expire_s=settings.briefing_expire_h * 3600),
            RemindersMonitor(lead_s=settings.reminder_lead_min * 60),
            CalendarMonitor(lead_s=settings.event_lead_min * 60),
            MailMonitor(),
        ]
    else:
        # 비맥: psutil 배터리 + 시간 기반 브리핑(맥은 잠금해제 브리핑이 담당)
        mons += [
            PsutilBatteryMonitor(levels=settings.battery_warn_levels),
            MorningBriefingMonitor(hour=getattr(settings, "briefing_hour", 8)),
        ]
    mons.append(SelfCheckMonitor())
    if timers is not None:
        mons.append(TimerMonitor(timers))
    if settings.proactive_late_night:
        mons.append(LateNightMonitor())
    return mons


class PsutilBatteryMonitor:
    """크로스플랫폼 배터리(psutil) — 윈도우/리눅스용. 맥은 pmset 기반이 기존 담당.
    문턱 하향 돌파/전원 전이만 알린다(BatteryMonitor와 같은 규약)."""

    interval_s = 60.0

    def __init__(self, levels=(20, 10, 5), reader=None, clock=time.monotonic):
        self._levels = sorted(levels, reverse=True)
        self._reader = reader
        self._clock = clock
        self._prev_ac: bool | None = None
        self._warned: set[int] = set()

    def _read(self):
        try:
            if self._reader is not None:
                return self._reader()
            import psutil  # noqa: PLC0415
            b = psutil.sensors_battery()
            if b is None:
                return None
            return int(b.percent), bool(b.power_plugged)
        except Exception:  # noqa: BLE001 - 이번 폴링만 건너뜀
            return None

    def poll(self) -> list[Announcement]:
        read = self._read()
        if read is None:
            return []
        pct, on_ac = read
        now = self._clock()
        out: list[Announcement] = []
        if self._prev_ac is not None and on_ac != self._prev_ac and on_ac:
            out.append(Announcement("charger_on", f"전원이 연결됐다 (배터리 {pct}%)",
                                    3, now, now + _FIVE_MIN))
            self._warned.clear()
        if not on_ac:
            for lv in self._levels:
                if pct <= lv and lv not in self._warned:
                    self._warned.add(lv)
                    out.append(Announcement(
                        "battery_low", f"배터리가 {pct}%다 — 충전을 권하라",
                        0 if lv <= 5 else 1, now, now + _TEN_MIN))
                    break
        self._prev_ac = on_ac
        return out


class MorningBriefingMonitor:
    """시간 기반 아침 브리핑(플랫폼 무관) — 설정 시각이 지나면 하루 1회.
    맥의 SessionMonitor 브리핑(첫 잠금해제)과 kind가 같아 엔진 쿨다운이 중복을 막는다."""

    interval_s = 60.0

    def __init__(self, *, hour: int = 8, clock=time.monotonic,
                 now_fn=datetime.now, today_fn=date.today):
        self._hour = hour
        self._clock = clock
        self._now = now_fn
        self._today = today_fn
        self._briefed_on: date | None = None

    def poll(self) -> list[Announcement]:
        if self._briefed_on == self._today():
            return []
        if self._now().hour < self._hour:
            return []
        self._briefed_on = self._today()
        now = self._clock()
        return [Announcement(
            "briefing",
            _BRIEFING_PROMPT,
            2, now, now + 7200.0)]


class MailMonitor:
    """새 메일 도착(맥, AppleScript 읽기전용) — 안 읽은 수가 '늘어난' 순간만 알린다."""

    interval_s = 120.0

    def __init__(self, *, runner=subprocess.run, clock=time.monotonic):
        self._runner = runner
        self._clock = clock
        self._prev: int | None = None

    def _unread(self) -> int | None:
        try:
            res = self._runner(
                ["osascript", "-e",
                 'tell application "Mail" to get unread count of inbox'],
                capture_output=True, text=True, timeout=10)
            return int((getattr(res, "stdout", "") or "").strip())
        except Exception:  # noqa: BLE001 - 메일 앱 꺼짐/권한 거부: 이번 폴링만 건너뜀
            return None

    def poll(self) -> list[Announcement]:
        n = self._unread()
        if n is None:
            return []
        out: list[Announcement] = []
        now = self._clock()
        if self._prev is not None and n > self._prev:
            new = n - self._prev
            out.append(Announcement(
                "new_mail",
                f"새 메일 {new}통이 도착했다 — get_unread_mail 도구로 보낸 사람과 "
                "제목만 확인해 짧게 알려라",
                3, now, now + _TEN_MIN))
        self._prev = n
        return out


class SelfCheckMonitor:
    """주기 자가점검 — '새로' 생긴 이상만 알린다(같은 이상 반복 보고 금지)."""

    interval_s = 1800.0

    def __init__(self, *, checker=None, clock=time.monotonic):
        self._checker = checker
        self._clock = clock
        self._known_bad: set[str] = set()

    def poll(self) -> list[Announcement]:
        try:
            if self._checker is not None:
                checks = self._checker()
            else:
                from ..core.selfcheck import run_checks  # noqa: PLC0415
                checks = run_checks()
        except Exception:  # noqa: BLE001 - 진단 실패가 엔진을 멈추면 안 된다
            return []
        bad = {c.name: c.detail for c in checks if not c.ok}
        fresh = {k: v for k, v in bad.items() if k not in self._known_bad}
        self._known_bad = set(bad)
        if not fresh:
            return []
        now = self._clock()
        items = "; ".join(f"{k}({v[:40]})" for k, v in fresh.items())
        return [Announcement(
            "selfcheck_warn",
            f"자가점검에서 새 이상 발견: {items} — 짧게 알리고 필요하면 self_check로 "
            "상세를 패널에 띄워라",
            2, now, now + _ONE_HOUR)]
