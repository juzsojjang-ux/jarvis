from types import SimpleNamespace

from jarvis.proactive.sources import fetch_events, fetch_reminders


def _runner_returning(stdout):
    calls = []

    def runner(cmd, capture_output=True, text=True, timeout=None):
        calls.append((cmd, timeout))
        return SimpleNamespace(stdout=stdout, returncode=0)

    runner.calls = calls
    return runner


def test_fetch_reminders_parses_lines():
    r = _runner_returning("id-1|회의 자료 제출|540\nid-2|약 먹기|3000\n")
    items = fetch_reminders(3600, runner=r)
    assert items == [("id-1", "회의 자료 제출", 540), ("id-2", "약 먹기", 3000)]
    cmd, timeout = r.calls[0]
    assert cmd[0] == "osascript" and timeout == 15


def test_fetch_skips_malformed_lines():
    r = _runner_returning("쓰레기줄\nid-1|제목|60\n|빈아이디|10\nid-2|음수|-5\n")
    items = fetch_reminders(3600, runner=r)
    assert items == [("id-1", "제목", 60)]   # 형식 불량·빈 id·지난 항목 제외


def test_fetch_events_parses_lines():
    r = _runner_returning("uid-9|팀 미팅|480\n")
    assert fetch_events(7200, runner=r) == [("uid-9", "팀 미팅", 480)]


def test_fetch_returns_empty_on_runner_error():
    def boom(cmd, capture_output=True, text=True, timeout=None):
        raise RuntimeError("osascript fail")

    assert fetch_reminders(3600, runner=boom) == []
    assert fetch_events(3600, runner=boom) == []
