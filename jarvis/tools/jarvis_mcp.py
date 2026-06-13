"""JARVIS capability tools, exposed to the subscription brain as an in-process SDK MCP
server. These let JARVIS actually DO things — tell the time, check weather, open Mac
apps, set the volume, remember notes — like the real assistant, while Bash/file-edit
stay forbidden so a misheard sentence can never run arbitrary code or touch the disk.

All actions are narrow and safe: `open -a <app>` only launches, `osascript set volume`
only adjusts output volume, weather is a keyless Open-Meteo call, remember appends to the
memory file. Helpers take an injectable `runner`/`fetch` so they're unit-testable.
"""
from __future__ import annotations

import asyncio
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


def _is_mac() -> bool:
    return sys.platform == "darwin"

from claude_agent_sdk import create_sdk_mcp_server, tool

from ..proactive.sources import fetch_events, fetch_reminders
from ..proactive.timers import DEFAULT_BOARD
from ..core.control_gate import CONTROL_GATE

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


def _fmt_due(title: str, secs: int) -> str:
    mins = max(1, secs // 60)
    if mins >= 60:
        return f"{title} — {mins // 60}시간 {mins % 60}분 후"
    return f"{title} — {mins}분 후"


def reminders_text(hours: Any = 24, fetch=fetch_reminders) -> str:
    try:
        h = max(1, min(168, int(hours)))
    except (TypeError, ValueError):
        h = 24
    items = fetch(h * 3600)
    if not items:
        return f"앞으로 {h}시간 안에 예정된 미리알림이 없습니다."
    lines = [_fmt_due(t, s) for _, t, s in items[:10]]
    return f"다가오는 미리알림 {len(items)}건: " + " / ".join(lines)


def calendar_text(hours: Any = 24, fetch=fetch_events) -> str:
    try:
        h = max(1, min(168, int(hours)))
    except (TypeError, ValueError):
        h = 24
    items = fetch(h * 3600)
    if not items:
        return f"앞으로 {h}시간 안에 캘린더 일정이 없습니다."
    lines = [_fmt_due(t, s) for _, t, s in items[:10]]
    return f"다가오는 일정 {len(items)}건: " + " / ".join(lines)


def battery_action(runner=subprocess.run) -> str:
    res = runner(["pmset", "-g", "batt"], capture_output=True, text=True)
    out = (getattr(res, "stdout", "") or "")
    import re
    m = re.search(r"(\d+)%", out)
    state = "충전 중" if "AC Power" in out or "charging" in out.lower() else "배터리 사용 중"
    return f"배터리 {m.group(1)}%입니다, {state}." if m else "배터리 상태를 읽지 못했습니다."


def set_timer_action(board, minutes=0, seconds=0, label: str = "") -> str:
    try:
        total = float(minutes or 0) * 60 + float(seconds or 0)
    except (TypeError, ValueError):
        return "몇 분짜리 타이머인지 말씀해 주세요."
    if total <= 0:
        return "몇 분짜리 타이머인지 말씀해 주세요."
    _tid, lb = board.add(total, label)
    m, s = int(total) // 60, int(total) % 60
    dur = (f"{m}분 " if m else "") + (f"{s}초" if s else "")
    return f"'{lb}' 타이머 {dur.strip()} 시작했습니다. 완료되면 알려드리겠습니다."


def cancel_timer_action(board, label: str = "") -> str:
    return board.cancel(label)


def list_timers_action(board) -> str:
    items = board.listing()
    if not items:
        return "진행 중인 타이머가 없습니다."
    return " / ".join(f"{lb}: {s // 60}분 {s % 60}초 남음" for lb, s in items)


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


def clipboard_read_action(runner=subprocess.run) -> str:
    res = runner(["pbpaste"], capture_output=True, text=True, timeout=10)
    out = (getattr(res, "stdout", "") or "").strip()
    if not out:
        return "클립보드가 비어 있습니다."
    if len(out) > 4000:  # 두뇌 컨텍스트 보호 — 긴 본문은 잘라서
        out = out[:4000] + " …(이하 생략)"
    return f"클립보드 내용: {out}"


def clipboard_write_action(text: str, runner=subprocess.run) -> str:
    if not (text or "").strip():
        return "복사할 내용을 말씀해 주세요."
    runner(["pbcopy"], capture_output=True, text=True, timeout=10, input=text)
    return "클립보드에 복사했습니다."


def run_shortcut_action(name: str, runner=subprocess.run) -> str:
    name = (name or "").strip()
    if not name:
        return "어느 단축어를 실행할까요?"
    try:
        res = runner(["shortcuts", "run", name], capture_output=True, text=True, timeout=30)
    except Exception:  # noqa: BLE001 - 타임아웃 포함: 실행은 백그라운드에서 계속된다
        return f"'{name}' 단축어가 30초 안에 끝나지 않았습니다 — 백그라운드에서 계속됩니다."
    if getattr(res, "returncode", 1) != 0:
        return f"'{name}' 단축어 실행에 실패했습니다. list_shortcuts로 정확한 이름을 확인하세요."
    out = (getattr(res, "stdout", "") or "").strip()
    return f"'{name}' 단축어를 실행했습니다." + (f" 결과: {out[:500]}" if out else "")


def list_shortcuts_action(runner=subprocess.run) -> str:
    res = runner(["shortcuts", "list"], capture_output=True, text=True, timeout=15)
    names = [ln.strip() for ln in (getattr(res, "stdout", "") or "").splitlines() if ln.strip()]
    if not names:
        return "만들어 둔 단축어가 없습니다."
    head = ", ".join(names[:20])
    more = f" 외 {len(names) - 20}개" if len(names) > 20 else ""
    return f"단축어 {len(names)}개: {head}{more}"


_SCREENSHOT_PATH = Path.home() / ".jarvis" / "screenshots" / "shot.png"


def capture_screen_action(runner=subprocess.run, path: Path | None = None) -> str:
    """화면을 무음 캡처해 파일로 저장하고 경로를 반환한다 — 두뇌가 Read로 본다.
    레티나 캡처(이미지 dpi 144)를 포인트 크기로 줄여 이미지 좌표를 cliclick 좌표와
    일치시킨다 — 데스크톱 전체 너비가 아니라 이미지 자신의 DPI를 쓰므로 멀티 모니터에서도
    안전하다(보정 실패는 무시)."""
    target = Path(path) if path is not None else _SCREENSHOT_PATH
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if not _is_mac():
            from jarvis.tools.win_control import capture
            try:
                capture(target)
                return f"화면을 캡처했습니다. 이 이미지를 Read 도구로 보세요: {target}"
            except Exception:  # noqa: BLE001
                return "화면 캡처에 실패했습니다. 화면 권한을 확인해 주세요."
        res = runner(["screencapture", "-x", str(target)],
                     capture_output=True, text=True)
        if getattr(res, "returncode", 1) != 0:
            return ("화면 캡처에 실패했습니다. 시스템 설정의 화면 기록 권한을 "
                    "확인해 주세요.")
        try:
            info = runner(["sips", "-g", "dpiWidth", "-g", "pixelWidth", str(target)],
                          capture_output=True, text=True)
            props = {}
            for line in str(info.stdout).splitlines():
                if ":" in line:
                    k, v = line.rsplit(":", 1)
                    props[k.strip()] = v.strip()
            scale = round(float(props["dpiWidth"]) / 72.0)
            if scale > 1:
                width = int(props["pixelWidth"]) // scale
                runner(["sips", "--resampleWidth", str(width), str(target)],
                       capture_output=True, text=True)
        except Exception:  # noqa: BLE001 - 보정은 최선 노력
            pass
        return f"화면을 캡처했습니다. 이 이미지를 Read 도구로 보세요: {target}"
    except Exception:  # noqa: BLE001 - 도구는 절대 raise하지 않는다
        return "화면 캡처에 실패했습니다."


_CLICK_PREFIX = {"click": "c", "double_click": "dc", "right_click": "rc", "move": "m"}


# 조준 보조(접근성 클릭): 픽셀이 아니라 '이름'으로 UI 요소를 찾아 누른다. 두뇌의 약한
# 좌표 조준을 우회한다 — 특히 메뉴·버튼·macOS 파일창에서 강력하다. AXPress가 되면
# 좌표 없이 누르고, 안 되면 요소 중심 좌표를 돌려준다(cliclick로 클릭).
_AX_CLICK_SCRIPT = '''on run argv
  set q to item 1 of argv
  set wantRole to ""
  if (count of argv) > 1 then set wantRole to item 2 of argv
  with timeout of 18 seconds
    tell application "System Events"
      try
        set p to first application process whose frontmost is true
      on error
        return "NOAPP"
      end try
      tell p
        try
          set w to window 1
        on error
          return "NOWIN"
        end try
        set cands to {}
        try
          set cands to entire contents of w
        end try
        repeat with el in cands
          try
            if wantRole is not "" then
              if (role of el) is not wantRole then error "skip"
            end if
            set nm to ""
            try
              set nm to (title of el) as text
            end try
            if nm is "" then
              try
                set nm to (description of el) as text
              end try
            end if
            if nm is "" then
              try
                set nm to (name of el) as text
              end try
            end if
            set hv to ""
            try
              set hv to (help of el) as text
            end try
            if (nm contains q) or (hv contains q) then
              try
                perform action "AXPress" of el
                return "PRESSED:" & nm
              on error
                set pos to position of el
                set sz to size of el
                set cx to (item 1 of pos) + ((item 1 of sz) div 2)
                set cy to (item 2 of pos) + ((item 2 of sz) div 2)
                return "POS:" & cx & "," & cy
              end try
            end if
          end try
        end repeat
      end tell
    end tell
  end timeout
  return "NOTFOUND"
end run'''


def ui_click_action(label: str, role: str = "", gate=None, runner=subprocess.run) -> str:
    """화면 요소를 '이름'으로 찾아 누른다(조준 보조). 게이트 필요(화면 제어 모드)."""
    g = gate if gate is not None else CONTROL_GATE
    if not g.is_on():
        return "화면 제어 모드가 꺼져 있습니다. 먼저 화면 제어 모드를 켜주세요."
    label = str(label or "").strip()
    if not label:
        return "누를 요소의 이름(보이는 글자)을 알려주세요."
    if not _is_mac():
        return "조준 보조 클릭은 현재 macOS에서만 지원합니다(윈도우는 좌표 클릭 사용)."
    try:
        res = runner(["osascript", "-e", _AX_CLICK_SCRIPT, label, str(role or "")],
                     capture_output=True, text=True, timeout=25)
    except subprocess.TimeoutExpired:
        return f"'{label}' 탐색이 오래 걸려 멈췄습니다 — 좌표 클릭으로 시도하세요."
    except Exception:  # noqa: BLE001
        return "조준 보조 클릭에 실패했습니다(손쉬운 사용 권한 확인)."
    out = (getattr(res, "stdout", "") or "").strip()
    if out.startswith("PRESSED:"):
        return f"'{out[8:].strip() or label}'을(를) 눌렀습니다."
    if out.startswith("POS:"):
        try:
            xs, ys = out[4:].split(",")
            runner(["cliclick", f"c:{int(float(xs))},{int(float(ys))}"],
                   capture_output=True, text=True, timeout=5)
            return f"'{label}' 위치를 눌렀습니다."
        except Exception:  # noqa: BLE001
            return f"'{label}'을 찾았으나 클릭에 실패했습니다."
    if out in ("NOWIN", "NOAPP"):
        return "현재 활성 창을 찾지 못했습니다 — 대상 앱을 앞으로 가져와 주세요."
    return (f"'{label}' 라는 요소를 화면에서 못 찾았습니다. 보이는 정확한 글자로 "
            "다시 시도하거나, 좌표 클릭(screen_control)을 쓰세요.")


def screen_control_action(action: str, x: Any = None, y: Any = None, text: str = "",
                          key: str = "", amount: Any = None,
                          gate=None, runner=subprocess.run, watch: bool = True) -> str:
    """좌표 기반 화면 조작(cliclick). '화면 제어 모드' 게이트가 꺼져 있으면 거부 —
    모드 진입 자체가 사용자 동의라서 모드 안에서는 동작별 음성 확인 없이 실행한다.

    watch=True면 동작 직후 화면을 자동 재캡처해 결과를 바로 '보게' 한다(계속 보면서
    작업). 별도 capture 턴이 필요 없어 두뇌가 see→act→see 루프를 빠르게 돈다."""
    g = gate if gate is not None else CONTROL_GATE
    if not g.is_on():
        return ("화면 제어 모드가 꺼져 있습니다. 먼저 '화면 제어 모드 켜줘'라고 "
                "말씀해 주세요.")
    action = str(action or "").strip()
    if action in _CLICK_PREFIX:
        try:
            args = [f"{_CLICK_PREFIX[action]}:{int(x)},{int(y)}"]
        except (TypeError, ValueError):
            return "좌표 x, y를 정수로 알려주세요."
        done = {"click": "클릭했습니다", "double_click": "더블클릭했습니다",
                "right_click": "우클릭했습니다", "move": "이동했습니다"}[action]
    elif action == "type":
        text = str(text or "")
        if not text.strip():
            return "입력할 텍스트가 비어 있습니다."
        args = [f"t:{text}"]
        done = "입력했습니다"
    elif action == "key":
        key = str(key or "").strip()
        if not key:
            return "누를 키 이름이 비어 있습니다(return, tab, esc, space, arrow-down 등)."
        args = [f"kp:{key}"]
        done = f"{key} 키를 눌렀습니다"
    elif action == "scroll":
        # cliclick엔 스크롤 명령이 없다 — page-up/down 키로 구현(양수=위).
        try:
            n = int(amount if amount is not None else 1)
        except (TypeError, ValueError):
            return "스크롤 양은 정수로 알려주세요(양수 위, 음수 아래)."
        if n == 0:
            return "스크롤 양이 0입니다."
        k = "page-up" if n > 0 else "page-down"
        args = [f"kp:{k}"] * min(abs(n), 10)
        done = "스크롤했습니다"
    else:
        return ("지원하지 않는 동작입니다. click, double_click, right_click, move, "
                "type, key, scroll 중 하나를 쓰세요.")
    if _is_mac():
        try:
            res = runner(["cliclick", *args], capture_output=True, text=True)
        except FileNotFoundError:
            return ("화면 제어에는 cliclick이 필요합니다. 터미널에서 "
                    "brew install cliclick 을 실행해 주세요.")
        except Exception:  # noqa: BLE001
            return "화면 조작에 실패했습니다."
        if getattr(res, "returncode", 0) != 0:
            return "화면 조작에 실패했습니다. 손쉬운 사용(접근성) 권한을 확인해 주세요."
    else:
        from jarvis.tools.win_control import perform
        try:
            perform(action, x=x, y=y, text=text, key=key, amount=amount)
        except Exception:  # noqa: BLE001
            return "화면 조작에 실패했습니다. 접근성/입력 권한을 확인해 주세요."
    if watch:
        # 동작 결과를 즉시 다시 본다 — 잠깐 렌더 대기 후 자동 재캡처(계속 보기).
        import time
        time.sleep(0.35)
        shot = capture_screen_action(runner=runner)
        if "캡처했습니다" in shot:
            return (f"{done}. 결과 화면을 갱신했습니다 — 반드시 Read 도구로 "
                    f"{_SCREENSHOT_PATH} 를 다시 보고 다음 동작을 결정하세요.")
    return f"{done}."


_MUSIC_FIND = {
    "track": 'play (first track of library playlist 1 whose name contains "{q}")',
    "artist": 'play (first track of library playlist 1 whose artist contains "{q}")',
    "album": 'play (first track of library playlist 1 whose album contains "{q}")',
    "playlist": 'play (first user playlist whose name contains "{q}")',
}


def play_music_action(query: str, kind: str = "any", runner=subprocess.run) -> str:
    q = (query or "").strip().replace('"', '\\"')
    if not q:
        return "무엇을 틀까요?"
    order = [kind] if kind in _MUSIC_FIND else ["track", "artist", "playlist"]
    for k in order:
        body = _MUSIC_FIND[k].replace("{q}", q)
        try:
            res = runner(["osascript", "-e", f'tell application "Music" to {body}'],
                         capture_output=True, text=True, timeout=15)
            if getattr(res, "returncode", 1) == 0:
                now = _osa('tell application "Music" to if player state is playing then '
                           'return (name of current track) & " — " & (artist of current track)',
                           runner)
                return f"재생합니다: {now}" if now else "재생을 시작했습니다."
        except Exception:  # noqa: BLE001 - 한 종류 실패는 다음으로, 도구는 raise 금지
            continue
    return (f"라이브러리에서 '{query}'를 찾지 못했습니다. "
            "(애플뮤직 카탈로그 검색은 지원하지 않습니다 — 라이브러리에 있는 것만)")


def _parse_pipe_lines(raw: str, limit: int) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for line in (raw or "").splitlines():
        parts = line.split("|", 1)
        if len(parts) == 2 and parts[0].strip():
            out.append((parts[0].strip(), parts[1].strip()))
        if len(out) >= limit:
            break
    return out


def messages_text(count: Any = 5, runner=subprocess.run) -> str:
    try:
        n = max(1, min(20, int(count)))
    except (TypeError, ValueError):
        n = 5
    script = (
        'set out to ""\n'
        'tell application "Messages"\n'
        '  set theChats to chats\n'
        '  repeat with c in theChats\n'
        '    try\n'
        '      set m to last text message of c\n'
        '      set out to out & (get name of c) & "|" & (get text of m) & linefeed\n'
        '    end try\n'
        '  end repeat\n'
        'end tell\n'
        'return out\n'
    )
    try:
        res = runner(["osascript", "-e", script], capture_output=True, text=True,
                     timeout=15)
        items = _parse_pipe_lines(getattr(res, "stdout", "") or "", n)
    except Exception:  # noqa: BLE001 - 권한·앱부재: 안내만
        return "메시지를 읽지 못했습니다(권한을 확인해 주세요)."
    if not items:
        return "최근 메시지가 없습니다."
    return "최근 메시지 " + " / ".join(f"{who}: {body}" for who, body in items)


def send_message_action(recipient: str, text: str, runner=subprocess.run) -> str:
    recipient = (recipient or "").strip()
    text = (text or "").strip()
    if not recipient or not text:
        return "받는 사람과 내용을 알려주세요."
    # 값은 osascript argv로 넘긴다(문자열 보간 금지) — 따옴표·역슬래시·개행이
    # 들어와도 AppleScript를 깨거나 탈출시킬 수 없다. 셸도 거치지 않는다.
    script = (
        'on run argv\n'
        '  set r to item 1 of argv\n'
        '  set t to item 2 of argv\n'
        '  tell application "Messages"\n'
        '    set targetService to 1st account whose service type = iMessage\n'
        '    set targetBuddy to participant r of targetService\n'
        '    send t to targetBuddy\n'
        '  end tell\n'
        'end run'
    )
    try:
        res = runner(["osascript", "-e", script, "--", recipient, text],
                     capture_output=True, text=True)
        if getattr(res, "returncode", 0) != 0:
            return f"{recipient}에게 메시지를 보내지 못했습니다(권한·수신자를 확인해 주세요)."
        return f"{recipient}에게 메시지를 보냈습니다."
    except Exception:  # noqa: BLE001 - 도구는 절대 raise하지 않는다
        return f"{recipient}에게 메시지를 보내지 못했습니다."


def send_mail_action(to: str, subject: str = "", body: str = "",
                     runner=subprocess.run) -> str:
    to = (to or "").strip()
    if not to:
        return "받는 사람을 알려주세요."
    # 값은 osascript argv로 넘긴다 — 개행 포함 본문도 안전하고 탈출 불가.
    script = (
        'on run argv\n'
        '  set theTo to item 1 of argv\n'
        '  set theSubject to item 2 of argv\n'
        '  set theBody to item 3 of argv\n'
        '  tell application "Mail"\n'
        '    set m to make new outgoing message with properties '
        '{subject:theSubject, content:theBody, visible:false}\n'
        '    tell m to make new to recipient at end of to recipients with properties '
        '{address:theTo}\n'
        '    send m\n'
        '  end tell\n'
        'end run'
    )
    try:
        res = runner(["osascript", "-e", script, "--", to, subject or "", body or ""],
                     capture_output=True, text=True)
        if getattr(res, "returncode", 0) != 0:
            return f"{to}에게 메일을 보내지 못했습니다(권한·메일 설정을 확인해 주세요)."
        return f"{to}에게 메일을 보냈습니다."
    except Exception:  # noqa: BLE001 - 도구는 절대 raise하지 않는다
        return f"{to}에게 메일을 보내지 못했습니다."


def mail_text(count: Any = 5, runner=subprocess.run) -> str:
    try:
        n = max(1, min(20, int(count)))
    except (TypeError, ValueError):
        n = 5
    script = (
        'set out to ""\n'
        'tell application "Mail"\n'
        '  set unread to (messages of inbox whose read status is false)\n'
        '  repeat with m in unread\n'
        '    set out to out & (sender of m) & "|" & (subject of m) & linefeed\n'
        '  end repeat\n'
        'end tell\n'
        'return out\n'
    )
    try:
        res = runner(["osascript", "-e", script], capture_output=True, text=True,
                     timeout=15)
        items = _parse_pipe_lines(getattr(res, "stdout", "") or "", n)
    except Exception:  # noqa: BLE001
        return "메일을 읽지 못했습니다(권한을 확인해 주세요)."
    if not items:
        return "안 읽은 메일이 없습니다."
    return f"안 읽은 메일 {len(items)}건: " + " / ".join(
        f"{who} — {subj}" for who, subj in items)


def control_mac_action(script: str, runner=subprocess.run) -> str:
    script = (script or "").strip()
    if not script:
        return "무엇을 할까요?"
    out = _osa(script, runner)
    return out or "완료했습니다."


_BRIGHT_KEYS = {"brightness_up": 144, "brightness_down": 145}
_ON_WORDS = ("on", "true", "1", "켜", "켜줘", "켜기")
_OFF_WORDS = ("off", "false", "0", "꺼", "꺼줘", "끄기")


def _wifi_device(runner=subprocess.run) -> str:
    """Wi-Fi 인터페이스명 탐지 — 기기마다 en0이 아닐 수 있다(USB 어댑터 등)."""
    res = runner(["networksetup", "-listallhardwareports"], capture_output=True,
                 text=True, timeout=10)
    take_next = False
    for line in (getattr(res, "stdout", "") or "").splitlines():
        if "Wi-Fi" in line or "AirPort" in line:
            take_next = True
        elif take_next and line.startswith("Device:"):
            return line.split(":", 1)[1].strip()
    return "en0"


def system_toggle_action(target: str, state: str = "toggle", runner=subprocess.run) -> str:
    target = (target or "").strip().lower()
    state = (state or "toggle").strip().lower()
    on = any(w in state for w in _ON_WORDS)
    off = any(w in state for w in _OFF_WORDS)
    try:
        if target in ("dark_mode", "darkmode", "다크모드"):
            value = "not dark mode" if not (on or off) else ("true" if on else "false")
            _osa("tell application \"System Events\" to tell appearance preferences "
                 f"to set dark mode to {value}", runner)
            word = "전환했" if not (on or off) else ("켰" if on else "껐")
            return f"다크 모드를 {word}습니다."
        if target in ("wifi", "wi-fi", "와이파이"):
            if not (on or off):
                return "와이파이는 켜기/끄기로 말씀해 주세요."
            dev = _wifi_device(runner)
            runner(["networksetup", "-setairportpower", dev, "on" if on else "off"],
                   capture_output=True, text=True, timeout=10)
            return f"와이파이를 {'켰' if on else '껐'}습니다."
        if target in ("bluetooth", "블루투스"):
            if not (on or off):
                return "블루투스는 켜기/끄기로 말씀해 주세요."
            runner(["blueutil", "-p", "1" if on else "0"],
                   capture_output=True, text=True, timeout=10)
            return f"블루투스를 {'켰' if on else '껐'}습니다."
        if target in _BRIGHT_KEYS:
            for _ in range(4):  # 호출당 4단계(약 25%) — 더 원하면 다시 부탁받는다
                _osa(f'tell application "System Events" to key code {_BRIGHT_KEYS[target]}',
                     runner)
            return "밝기를 조절했습니다."
        if target in ("display_off", "화면끄기"):
            runner(["pmset", "displaysleepnow"], capture_output=True, text=True, timeout=10)
            return "화면을 껐습니다."
        if target == "sleep" or "절전" in target:
            runner(["pmset", "sleepnow"], capture_output=True, text=True, timeout=10)
            return "절전 모드로 들어갑니다, 주인님."
    except FileNotFoundError as exc:
        return (f"{exc.args[0] if exc.args else '필요한 명령'}이 설치되어 있지 않습니다. "
                "블루투스 제어는 'brew install blueutil'이 필요합니다.")
    except Exception:  # noqa: BLE001 - 도구는 절대 raise하지 않는다(두뇌가 말로 전달)
        return "시스템 설정 변경에 실패했습니다."
    return ("지원하는 항목: 다크모드, 와이파이, 블루투스, 밝기(brightness_up/down), "
            "화면끄기(display_off), 절전(sleep). 방해금지는 단축어 앱에서 만들어 "
            "run_shortcut으로 실행할 수 있습니다.")


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


@tool("play_music", "음악 라이브러리에서 곡/아티스트/플레이리스트를 찾아 재생한다. "
      "kind: track|artist|album|playlist|any. 라이브러리 한정(카탈로그 검색 불가).",
      {"type": "object", "properties": {"query": {"type": "string"},
       "kind": {"type": "string"}}, "required": ["query"]})
async def _play_music(args):
    a = args or {}
    return _text(play_music_action(str(a.get("query", "")), str(a.get("kind", "any"))))


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


@tool("get_reminders", "다가오는 미리알림 목록을 읽는다(읽기 전용).",
      {"type": "object", "properties": {"hours": {"type": "integer"}}})
async def _get_reminders(args):
    return _text(reminders_text((args or {}).get("hours", 24)))


@tool("get_calendar_events", "다가오는 캘린더 일정을 읽는다(읽기 전용).",
      {"type": "object", "properties": {"hours": {"type": "integer"}}})
async def _get_calendar_events(args):
    return _text(calendar_text((args or {}).get("hours", 24)))


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


@tool("system_toggle",
      "맥 시스템 설정 전환: dark_mode/wifi/bluetooth/brightness_up/brightness_down/"
      "display_off/sleep. state는 on/off/toggle. 방해금지(DND)는 직접 지원하지 않음 — "
      "사용자가 단축어를 만들면 run_shortcut으로 가능하다고 안내하라.",
      {"type": "object", "properties": {"target": {"type": "string"},
       "state": {"type": "string"}}, "required": ["target"]})
async def _system_toggle(args):
    a = args or {}
    return _text(system_toggle_action(str(a.get("target", "")), str(a.get("state", "toggle"))))


@tool("clipboard_read", "클립보드의 텍스트를 읽는다(요약·낭독용).", {})
async def _clipboard_read(_args):
    return _text(clipboard_read_action())


@tool("clipboard_write", "텍스트를 클립보드에 복사한다.",
      {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]})
async def _clipboard_write(args):
    return _text(clipboard_write_action(str((args or {}).get("text", ""))))


@tool("run_shortcut", "macOS 단축어(Shortcuts) 앱의 단축어를 이름으로 실행한다. "
      "방해금지·스마트홈 등 확장은 사용자가 단축어를 만들면 전부 가능.",
      {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]})
async def _run_shortcut(args):
    return _text(run_shortcut_action(str((args or {}).get("name", ""))))


@tool("list_shortcuts", "사용 가능한 macOS 단축어 목록.", {})
async def _list_shortcuts(_args):
    return _text(list_shortcuts_action())


@tool("get_messages", "최근 받은 메시지를 읽는다(읽기 전용). 보내기는 하지 않는다.",
      {"type": "object", "properties": {"count": {"type": "integer"}}})
async def _get_messages(args):
    return _text(messages_text((args or {}).get("count", 5)))


@tool("get_unread_mail", "안 읽은 메일의 발신자·제목을 읽는다(읽기 전용).",
      {"type": "object", "properties": {"count": {"type": "integer"}}})
async def _get_unread_mail(args):
    return _text(mail_text((args or {}).get("count", 5)))


@tool("send_message", "iMessage로 메시지를 보낸다(발송 전 음성 확인 필요).",
      {"type": "object", "properties": {"recipient": {"type": "string"},
       "text": {"type": "string"}}, "required": ["recipient", "text"]})
async def _send_message(args):
    a = args or {}
    return _text(send_message_action(str(a.get("recipient") or ""), str(a.get("text") or "")))


@tool("send_mail", "메일을 보낸다(발송 전 음성 확인 필요).",
      {"type": "object", "properties": {"to": {"type": "string"}, "subject": {"type": "string"},
       "body": {"type": "string"}}, "required": ["to"]})
async def _send_mail(args):
    a = args or {}
    return _text(send_mail_action(str(a.get("to") or ""), str(a.get("subject") or ""),
                                  str(a.get("body") or "")))


@tool("set_timer", "타이머를 맞춘다(분/초/라벨). 완료되면 자비스가 음성으로 알린다.",
      {"type": "object", "properties": {"minutes": {"type": "number"},
       "seconds": {"type": "number"}, "label": {"type": "string"}}})
async def _set_timer(args):
    a = args or {}
    return _text(set_timer_action(DEFAULT_BOARD, a.get("minutes"), a.get("seconds"),
                                  str(a.get("label") or "")))


@tool("cancel_timer", "진행 중인 타이머를 취소한다.",
      {"type": "object", "properties": {"label": {"type": "string"}}})
async def _cancel_timer(args):
    return _text(cancel_timer_action(DEFAULT_BOARD, str((args or {}).get("label") or "")))


@tool("list_timers", "진행 중인 타이머 목록과 남은 시간을 알려준다.", {})
async def _list_timers(_args):
    return _text(list_timers_action(DEFAULT_BOARD))


@tool("capture_screen",
      "맥 화면을 캡처해 이미지 파일로 저장한다. 반환된 경로를 Read 도구로 읽으면 "
      "지금 화면을 직접 볼 수 있다. 화면 조작 전 좌표 파악에도 쓴다.", {})
async def _capture_screen(_args):
    return _text(capture_screen_action())


@tool("screen_control",
      "화면을 마우스·키보드로 조작한다(클릭/더블클릭/우클릭/이동/텍스트 입력/특수키/"
      "스크롤). 사용자가 '화면 제어 모드'를 켜둬야만 동작한다. 좌표는 먼저 "
      "capture_screen으로 화면을 본 뒤 그 이미지 픽셀 좌표를 그대로 쓴다.",
      {"type": "object", "properties": {
          "action": {"type": "string",
                     "enum": ["click", "double_click", "right_click", "move",
                              "type", "key", "scroll"]},
          "x": {"type": "integer"}, "y": {"type": "integer"},
          "text": {"type": "string"}, "key": {"type": "string"},
          "amount": {"type": "integer"}},
       "required": ["action"]})
async def _screen_control(args):
    a = args or {}
    return _text(screen_control_action(
        str(a.get("action") or ""), a.get("x"), a.get("y"),
        str(a.get("text") or ""), str(a.get("key") or ""), a.get("amount")))


@tool("click_by_name", "화면 제어의 '조준 보조' — 픽셀 좌표 대신 버튼/메뉴/링크를 보이는 "
      "글자(이름)로 찾아 누른다. 좌표 클릭(screen_control)보다 훨씬 정확하니, 누를 대상에 "
      "글자가 있으면 이걸 먼저 써라(예: name='새로 만들기', name='파일 업로드', name='열기'). "
      "못 찾으면 그때 capture+screen_control 좌표로 폴백. role로 종류 한정 가능(AXButton/"
      "AXMenuItem/AXMenuButton/AXStaticText 등). 화면 제어 모드가 켜져 있어야 한다.",
      {"type": "object", "properties": {"name": {"type": "string"},
       "role": {"type": "string"}}, "required": ["name"]})
async def _click_by_name(args):
    a = args or {}
    return _text(ui_click_action(str(a.get("name", "")), role=str(a.get("role", ""))))


@tool("show_panel", "화면 오른쪽 위 정보 패널(자비스 홀로그램)에 내용을 띄운다. 사용자가 "
      "'패널에 보여줘/띄워줘'라고 하거나, 목록·일정·요약·표처럼 눈으로 보면 좋은 정보를 "
      "전할 때 쓴다. content는 반드시 **한국어**로, 줄바꿈으로 또박또박 정리한다(고유명사/"
      "스코어 등 원어가 자연스러우면 그대로). 패널은 내용 양에 따라 자동으로 커진다 — "
      "짧은 알림은 작게, 긴 목록/표/상세 정보는 아주 크게(필요하면 스크롤). 그러니 정보가 "
      "많으면 줄이지 말고 풍부하게 정리해 넣어도 된다. 패널은 기본 숨김이니 도움될 때만 띄운다.",
      {"type": "object", "properties": {"content": {"type": "string"}}, "required": ["content"]})
async def _show_panel(args):
    from ..hud import notice_bus
    content = str((args or {}).get("content", "")).strip()
    if not content:
        return _text("무엇을 패널에 보여드릴까요?")
    ok = notice_bus.show(content)
    return _text("패널에 표시했습니다." if ok else "지금은 패널을 띄울 수 없습니다.")


@tool("hide_panel", "오른쪽 위 정보 패널을 닫는다(사용자가 '패널 꺼/닫아'라고 할 때).", {})
async def _hide_panel(_args):
    from ..hud import notice_bus
    notice_bus.hide()
    return _text("패널을 닫았습니다.")

@tool("self_check", "자비스 자가진단 — 마이크/두뇌/음성/로그/스킬/디스크 등 시스템 상태를 "
      "점검해 무엇이 문제인지 보고한다. 사용자가 '뭐가 문제야', '왜 안 돼', '상태 점검해', "
      "'자가진단 해봐'라고 하거나, 기능이 거듭 실패해 원인이 궁금할 때 스스로도 사용하라. "
      "결과는 한국어 보고서 — 그대로 패널(show_panel)에 띄우고 요점만 말로 전하면 좋다.", {})
async def _self_check(_args):
    from ..core.selfcheck import format_report, run_checks
    checks = await asyncio.to_thread(run_checks)
    return _text(format_report(checks))


@tool("consult_brain", "보조 두뇌(다른 LLM)에게 자문을 구한다 — provider는 'gemini' 또는 "
      "'gpt'. 사용자가 '제미나이한테 물어봐', 'GPT 의견은?', '교차 검증해줘'라고 하면 반드시 "
      "사용하고, 중요한 사실 판단·설계 결정·답이 갈릴 만한 질문은 묻지 않아도 스스로 자문해 "
      "답을 보강하라. 답을 전할 때는 출처를 밝힌다(예: '제미나이는 …라고 합니다'). "
      "보조 두뇌는 도구 없이 답만 하므로 컴퓨터 조작은 못 한다.",
      {"type": "object", "properties": {
          "provider": {"type": "string", "enum": ["gemini", "gpt"]},
          "question": {"type": "string"}},
       "required": ["provider", "question"]})
async def _consult_brain(args):
    from ..brain.consult import consult
    a = args or {}
    out = await consult(str(a.get("provider", "")), str(a.get("question", "")))
    return _text(out)

@tool("background_task", "긴 작업(조사·정리·다단계)을 백그라운드로 위임한다 — 대화를 막지 "
      "않고 뒤에서 별도 두뇌가 수행하며, 끝나면 자비스가 먼저 보고한다. 사용자가 '뒤에서 "
      "해놔', '백그라운드로', '조사해놓고 나중에 알려줘'라고 하거나, 작업이 수십 초 이상 "
      "걸릴 조사/리서치라면 이 도구로 넘기고 짧게 접수만 알려라.",
      {"type": "object", "properties": {"description": {"type": "string"}},
       "required": ["description"]})
async def _background_task(args):
    from ..core import bgtasks
    return _text(bgtasks.start(str((args or {}).get("description", ""))))


@tool("background_status", "백그라운드 작업들의 진행 상황을 확인한다('그 작업 어떻게 됐어').", {})
async def _background_status(_args):
    from ..core import bgtasks
    return _text(bgtasks.status_text())


@tool("recall_memory", "장기 기억(전체 대화 아카이브)에서 과거 대화를 검색한다. 사용자가 "
      "'지난번에/저번 주에/예전에 뭐라고 했지', '~한 적 있었나' 같은 과거 회상을 물으면 "
      "이 도구로 찾아 답하라. query는 핵심 단어 위주로.",
      {"type": "object", "properties": {"query": {"type": "string"}},
       "required": ["query"]})
async def _recall_memory(args):
    from ..brain.longmem import LongMemory
    q = str((args or {}).get("query", "")).strip()
    if not q:
        return _text("무엇을 찾을까요?")
    hits = LongMemory().search(q, k=5)
    if not hits:
        return _text("관련된 과거 대화를 찾지 못했습니다.")
    lines = [f"({h['ts']}) 사용자: {h['user'][:100]} / 자비스: {h['assistant'][:100]}"
             for h in hits]
    return _text("\n".join(lines))

@tool("create_skill", "새 능력(도구)을 자비스가 직접 코딩해 추가한다. 사용자가 '이런 기능 "
      "만들어줘'라고 하면 너가 파이썬 코드를 작성해 이 도구로 넘겨라 — 문법·계약을 "
      "검증한 뒤 ~/.jarvis/skills/<name>.py 로 저장한다(통과해야 저장됨). 코드 계약: "
      "모듈 레벨에 TOOLS=[{'name':str,'description':str(한국어),'parameters':JSON스키마,"
      "'handler':callable}], handler(args:dict)는 문자열 반환(동기/비동기 가능), "
      "stdlib만, 방어적(절대 raise 금지). 저장 후 재시작하면 활성화된다고 사용자에게 알려라.",
      {"type": "object", "properties": {
          "name": {"type": "string"}, "code": {"type": "string"}},
       "required": ["name", "code"]})
async def _create_skill(args):
    from .skillsmith import save_skill
    a = args or {}
    ok, msg = save_skill(str(a.get("name", "")), str(a.get("code", "")))
    return _text(msg)


@tool("list_skills", "자비스가 지금까지 자작한 스킬(추가 능력) 목록을 보여준다.", {})
async def _list_skills(_args):
    from .skillsmith import list_skills
    names = list_skills()
    return _text("자작 스킬: " + (", ".join(names) if names else "아직 없습니다."))


@tool("web_open", "자비스 전용 크롬(별도 프로필 — 사용자 크롬과 무관)으로 URL을 연다. "
      "웹 작업(업로드/폼/사이트 조작)은 픽셀 클릭(screen_control) 대신 반드시 이 web_* "
      "도구들을 써라 — DOM을 직접 다뤄 빗나가지 않는다. 결과로 페이지의 클릭 가능한 "
      "요소 번호 목록이 온다. 로그인이 필요한 사이트는 사용자가 그 창에서 직접 한 번 "
      "로그인하게 안내하라(세션은 유지된다).",
      {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]})
async def _web_open(args):
    from .webdrive import DRIVER
    try:
        return _text(await DRIVER.open(str((args or {}).get("url", ""))))
    except Exception as exc:
        return _text(f"웹 열기 실패: {exc}")


@tool("web_read", "현재 웹페이지의 제목/URL/클릭 가능한 요소 번호 목록을 다시 읽는다 — "
      "클릭/입력 후 상태 확인용.", {})
async def _web_read(_args):
    from .webdrive import DRIVER
    try:
        return _text(await DRIVER.read())
    except Exception as exc:
        return _text(f"웹 읽기 실패: {exc}")


@tool("web_click", "web_read 목록의 [번호] 요소를 클릭한다. 클릭 후 갱신된 요소 목록을 "
      "돌려준다.",
      {"type": "object", "properties": {"index": {"type": "integer"}},
       "required": ["index"]})
async def _web_click(args):
    from .webdrive import DRIVER
    try:
        return _text(await DRIVER.click(int((args or {}).get("index", -1))))
    except Exception as exc:
        return _text(f"웹 클릭 실패: {exc}")


@tool("web_type", "web_read 목록의 [번호] 입력칸에 텍스트를 넣는다. submit=true면 Enter.",
      {"type": "object", "properties": {
          "index": {"type": "integer"}, "text": {"type": "string"},
          "submit": {"type": "boolean"}},
       "required": ["index", "text"]})
async def _web_type(args):
    from .webdrive import DRIVER
    a = args or {}
    try:
        return _text(await DRIVER.type(int(a.get("index", -1)), str(a.get("text", "")),
                                       bool(a.get("submit", False))))
    except Exception as exc:
        return _text(f"웹 입력 실패: {exc}")


@tool("web_upload", "현재 페이지에 파일을 업로드한다(구글 드라이브 등) — 파일 선택 창 "
      "없이 DOM에 직접 꽂아 100% 결정적. index는 업로드 관련 요소 번호(모르면 0), "
      "paths는 절대경로 목록.",
      {"type": "object", "properties": {
          "index": {"type": "integer"},
          "paths": {"type": "array", "items": {"type": "string"}}},
       "required": ["paths"]})
async def _web_upload(args):
    from .webdrive import DRIVER
    a = args or {}
    try:
        return _text(await DRIVER.upload(int(a.get("index", 0)),
                                         [str(x) for x in (a.get("paths") or [])]))
    except Exception as exc:
        return _text(f"웹 업로드 실패: {exc}")


@tool("web_screenshot", "자비스 크롬 페이지를 스크린샷으로 저장하고 경로를 돌려준다 — "
      "Read 도구로 보면서 시각 확인.", {})
async def _web_screenshot(_args):
    from .webdrive import DRIVER
    try:
        path = await DRIVER.screenshot()
        return _text(f"저장했습니다 — Read 도구로 보세요: {path}")
    except Exception as exc:
        return _text(f"웹 스크린샷 실패: {exc}")





@tool("screen_control_mode", "화면 제어 모드를 켜거나 끈다. 사용자가 어떤 표현으로든 "
      "화면 제어(클릭/입력 조작)를 켜 달라고 하면 state='on'으로 호출한다 — 사용자에게 "
      "특정 문구를 다시 말하라고 하지 말 것. 몇 분 후 자동으로 꺼진다.",
      {"type": "object", "properties": {"state": {"type": "string", "enum": ["on", "off"]}},
       "required": ["state"]})
async def _screen_control_mode(args):
    state = str((args or {}).get("state", "")).strip().lower()
    if state == "on":
        CONTROL_GATE.enable(300.0)
        return _text("화면 제어 모드를 켰습니다. 몇 분 후 자동으로 꺼집니다.")
    if state == "off":
        CONTROL_GATE.disable()
        return _text("화면 제어 모드를 껐습니다.")
    return _text("state는 on 또는 off로 알려주세요.")


def _skill_sdk_tools():
    """~/.jarvis/skills/*.py 의 사용자/자비스 작성 스킬을 SDK 도구로 감싼다.

    스킬은 NeutralTool(파이썬 객체)로 로드되는데, Claude 구독 두뇌의 인프로세스
    MCP 서버는 @tool(SdkMcpTool)만 받는다 — 여기서 감싸지 않으면 클로드 두뇌만
    스킬을 못 쓰는 비대칭이 생긴다(자가 코딩 시연에서 발견된 통합 구멍)."""
    from .skills import load_skill_tools
    out = []
    for nt in load_skill_tools():
        async def _h(args, _nt=nt):
            return _text(await _nt.call(args or {}))
        out.append(tool(nt.name, nt.description, nt.parameters)(_h))
    return out


def build_tool_objects(memory: Any = None):
    """30개 SdkMcpTool 객체 리스트를 반환한다.

    MCP 서버와 프로바이더 중립 레지스트리가 같은 도구 정의를 공유하기 위해
    도구 리스트 구성 로직을 여기로 추출했다.  `remember` 도구는 `memory`를
    클로저로 캡처하므로 매 호출마다 새로 만든다.
    """

    @tool("remember", "사용자가 알려준 정보를 장기 기억에 저장한다.",
          {"type": "object", "properties": {"note": {"type": "string"}}, "required": ["note"]})
    async def _remember(args):
        note = str((args or {}).get("note", "")).strip()
        if not note:
            return _text("무엇을 기억할까요?")
        if memory is not None and hasattr(memory, "remember"):
            memory.remember(note)
        return _text(f"기억했습니다: {note}")

    return [_get_time, _get_weather, _open_app, _set_volume, _play_music, _music,
            _add_reminder, _create_note, _battery, _get_reminders, _get_calendar_events,
            _mute, _lock, _quit_app, _control_mac, _system_toggle,
            _clipboard_read, _clipboard_write, _run_shortcut, _list_shortcuts,
            _set_timer, _cancel_timer, _list_timers,
            _get_messages, _get_unread_mail,
            _send_message, _send_mail,
            _capture_screen, _screen_control, _screen_control_mode, _click_by_name,
            _show_panel, _hide_panel,
            _self_check, _consult_brain,
            _background_task, _background_status, _recall_memory,
            _create_skill, _list_skills,
            _web_open, _web_read, _web_click, _web_type, _web_upload, _web_screenshot,
            _remember,
            *_skill_sdk_tools()]  # 자가 확장 스킬 — 모든 두뇌(클로드 포함)가 사용


def build_jarvis_mcp_server(memory: Any = None):
    """In-process MCP server. `memory` (a MemoryStore) backs the remember tool."""
    return create_sdk_mcp_server("jarvis", "1.0.0", tools=build_tool_objects(memory))


# Allow-list names the brain passes to ClaudeAgentOptions.allowed_tools.
JARVIS_TOOL_NAMES = [f"mcp__jarvis__{n}" for n in (
    "get_time", "get_weather", "open_app", "set_volume", "play_music", "music_control",
    "add_reminder", "create_note", "battery_status", "get_reminders", "get_calendar_events",
    "toggle_mute", "lock_screen", "quit_app", "control_mac", "system_toggle",
    "clipboard_read", "clipboard_write", "run_shortcut", "list_shortcuts",
    "set_timer", "cancel_timer", "list_timers",
    "get_messages", "get_unread_mail",
    "send_message", "send_mail",
    "capture_screen", "screen_control",
    "self_check", "consult_brain",
    "background_task", "background_status", "recall_memory",
    "create_skill", "list_skills",
    "web_open", "web_read", "web_click", "web_type", "web_upload", "web_screenshot",
    "remember",
)]
