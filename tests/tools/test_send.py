from jarvis.tools.jarvis_mcp import send_message_action, send_mail_action


class _Res:
    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode; self.stdout = stdout


def _runner(calls, fail=False):
    def run(cmd, capture_output=True, text=True, timeout=None):
        calls.append(cmd)
        if fail:
            raise OSError("boom")
        return _Res()
    return run


def test_send_message_ok():
    calls = []
    out = send_message_action("민지", "곧 도착", runner=_runner(calls))
    assert "보냈습니다" in out
    joined = " ".join(calls[0])
    assert "민지" in joined and "곧 도착" in joined
    assert calls[0][0] == "osascript"


def test_send_message_empty_args():
    assert "알려" in send_message_action("", "hi", runner=_runner([]))
    assert "알려" in send_message_action("민지", "", runner=_runner([]))


def test_send_message_passes_values_as_argv_not_interpolated():
    """값은 argv로 — 따옴표·개행이 들어와도 스크립트 본문에 보간되지 않는다."""
    calls = []
    send_message_action("민지", 'say "hi"\nline2', runner=_runner(calls))
    cmd = calls[0]
    # 원문 그대로 argv 끝에 실린다(이스케이프·보간 없음)
    assert cmd[-2] == "민지" and cmd[-1] == 'say "hi"\nline2'
    # 스크립트 본문(-e 다음)엔 사용자 텍스트가 보간되지 않는다
    script = cmd[cmd.index("-e") + 1]
    assert "hi" not in script and "민지" not in script


def test_send_message_reports_failure_on_nonzero_returncode():
    def run(cmd, capture_output=True, text=True, timeout=None):
        return _Res(returncode=1)
    out = send_message_action("민지", "x", runner=run)
    assert "못" in out


def test_send_message_never_raises():
    out = send_message_action("민지", "x", runner=_runner([], fail=True))
    assert "못" in out or "실패" in out or "않" in out


def test_send_mail_ok():
    calls = []
    out = send_mail_action("a@b.com", "제목", "본문", runner=_runner(calls))
    assert "보냈습니다" in out
    joined = " ".join(calls[0])
    assert "a@b.com" in joined and "제목" in joined


def test_send_mail_empty_to():
    assert "알려" in send_mail_action("", "s", "b", runner=_runner([]))


def test_send_mail_optional_subject_body():
    calls = []
    out = send_mail_action("a@b.com", runner=_runner(calls))
    assert "보냈습니다" in out


def test_send_mail_body_with_newlines_is_argv():
    """메일 본문 개행 — argv라 안전(예전엔 AppleScript 컴파일을 깨뜨렸다)."""
    calls = []
    send_mail_action("a@b.com", "제목", "첫 줄\n둘째 줄", runner=_runner(calls))
    assert calls[0][-1] == "첫 줄\n둘째 줄"


def test_send_mail_reports_failure_on_nonzero_returncode():
    def run(cmd, capture_output=True, text=True, timeout=None):
        return _Res(returncode=1)
    out = send_mail_action("a@b.com", "s", "b", runner=run)
    assert "못" in out


def test_send_mail_never_raises():
    out = send_mail_action("a@b.com", "s", "b", runner=_runner([], fail=True))
    assert "못" in out or "실패" in out or "않" in out
