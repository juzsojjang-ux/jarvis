"""capture_screen / screen_control — 실제 screencapture·cliclick·osascript는 절대
실행하지 않는다(fake runner 주입)."""
from jarvis.tools.jarvis_mcp import capture_screen_action


class _Res:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.returncode = returncode


def _runner(calls, *, fail_capture=False):
    def run(cmd, capture_output=True, text=True):
        calls.append(list(cmd))
        if cmd[0] == "screencapture" and fail_capture:
            return _Res(returncode=1)
        if cmd[0] == "osascript":
            return _Res(stdout="0, 0, 1728, 1117\n")
        return _Res()
    return run


def test_capture_creates_dir_and_returns_path(tmp_path):
    calls = []
    target = tmp_path / "shots" / "shot.png"
    out = capture_screen_action(runner=_runner(calls), path=target)
    assert target.parent.is_dir()
    assert str(target) in out
    assert calls[0] == ["screencapture", "-x", str(target)]


def test_capture_resamples_to_point_width(tmp_path):
    calls = []
    target = tmp_path / "shot.png"
    capture_screen_action(runner=_runner(calls), path=target)
    sips = [c for c in calls if c[0] == "sips"]
    assert sips and sips[0][:3] == ["sips", "--resampleWidth", "1728"]


def test_capture_failure_returns_guidance(tmp_path):
    out = capture_screen_action(runner=_runner([], fail_capture=True),
                                path=tmp_path / "shot.png")
    assert "실패" in out and "권한" in out


def test_capture_never_raises(tmp_path):
    def boom(cmd, capture_output=True, text=True):
        raise OSError("no screen")
    out = capture_screen_action(runner=boom, path=tmp_path / "shot.png")
    assert "실패" in out


def test_capture_survives_bad_bounds(tmp_path):
    """osascript 보정 실패해도 캡처 경로는 반환."""
    def run(cmd, capture_output=True, text=True):
        if cmd[0] == "osascript":
            return _Res(stdout="garbage")
        return _Res()
    target = tmp_path / "shot.png"
    out = capture_screen_action(runner=run, path=target)
    assert str(target) in out
