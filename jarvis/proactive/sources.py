"""미리알림/캘린더를 AppleScript로 읽는다 — 감시자(임박 알림)와 MCP 도구
(브리핑·"오늘 일정 뭐야?")가 같은 페처를 쓴다. 출력 계약: (id, 제목, 남은초).
첫 호출 시 macOS 자동화 권한 팝업이 뜰 수 있다(부팅이 아니라 첫 폴링 시점)."""
from __future__ import annotations

import subprocess

_REMINDERS_SCRIPT = """
set out to ""
set nowD to current date
tell application "Reminders"
    repeat with r in (reminders whose completed is false)
        try
            set d to due date of r
            if d is not missing value then
                set secs to (d - nowD) as integer
                if secs > 0 and secs < {window} then
                    set out to out & (id of r) & "|" & (name of r) & "|" & secs & linefeed
                end if
            end if
        end try
    end repeat
end tell
return out
"""

_EVENTS_SCRIPT = """
set out to ""
set nowD to current date
set endD to nowD + {window}
tell application "Calendar"
    repeat with c in calendars
        try
            repeat with e in (events of c whose start date is greater than nowD ¬
                              and start date is less than endD)
                try
                    set secs to ((start date of e) - nowD) as integer
                    set out to out & (uid of e) & "|" & (summary of e) & "|" & secs & linefeed
                end try
            end repeat
        end try
    end repeat
end tell
return out
"""


def _run_script(script: str, runner) -> list[tuple[str, str, int]]:
    try:
        res = runner(["osascript", "-e", script], capture_output=True, text=True, timeout=15)
        raw = (getattr(res, "stdout", "") or "")
    except Exception:  # noqa: BLE001 - 권한 거부/타임아웃: 이번 폴링만 빈손
        return []
    items: list[tuple[str, str, int]] = []
    for line in raw.splitlines():
        parts = line.split("|")
        if len(parts) != 3:
            continue
        ident, title, secs_s = parts[0].strip(), parts[1].strip(), parts[2].strip()
        try:
            secs = int(secs_s)
        except ValueError:
            continue
        if ident and secs > 0:
            items.append((ident, title, secs))
    return items


def fetch_reminders(window_s: int, runner=subprocess.run) -> list[tuple[str, str, int]]:
    return _run_script(_REMINDERS_SCRIPT.replace("{window}", str(int(window_s))), runner)


def fetch_events(window_s: int, runner=subprocess.run) -> list[tuple[str, str, int]]:
    return _run_script(_EVENTS_SCRIPT.replace("{window}", str(int(window_s))), runner)
