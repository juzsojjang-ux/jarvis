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


def test_send_message_escapes_quotes():
    calls = []
    send_message_action("민지", 'say "hi"', runner=_runner(calls))
    joined = " ".join(calls[0])
    assert '\\"hi\\"' in joined  # quotes escaped


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


def test_send_mail_never_raises():
    out = send_mail_action("a@b.com", "s", "b", runner=_runner([], fail=True))
    assert "못" in out or "실패" in out or "않" in out
