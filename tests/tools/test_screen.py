"""capture_screen / screen_control — 실제 screencapture·cliclick·osascript는 절대
실행하지 않는다(fake runner 주입). 맥 분기 로직 검증이므로 어느 OS에서 돌든
_is_mac을 참으로 고정한다(윈도우 CI 포함)."""
import pytest

import jarvis.tools.jarvis_mcp as jm
from jarvis.tools.jarvis_mcp import capture_screen_action


@pytest.fixture(autouse=True)
def _force_mac_branch(monkeypatch):
    monkeypatch.setattr(jm, "_is_mac", lambda: True)


class _Res:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.returncode = returncode


def _runner(calls, *, fail_capture=False, dpi="144.000", pixel_w="3456"):
    def run(cmd, capture_output=True, text=True, **kwargs):  # timeout= 등 허용
        calls.append(list(cmd))
        if cmd[0] == "screencapture" and fail_capture:
            return _Res(returncode=1)
        if cmd[0] == "sips" and "-g" in cmd:
            return _Res(stdout=f"/tmp/shot.png\n  dpiWidth: {dpi}\n  pixelWidth: {pixel_w}\n")
        return _Res()
    return run


def test_capture_creates_dir_and_returns_path(tmp_path):
    calls = []
    target = tmp_path / "shots" / "shot.png"
    out = capture_screen_action(runner=_runner(calls), path=target)
    assert target.parent.is_dir()
    assert str(target) in out
    assert calls[0] == ["screencapture", "-x", str(target)]


def test_capture_resamples_retina_to_point_width(tmp_path):
    calls = []
    target = tmp_path / "shot.png"
    capture_screen_action(runner=_runner(calls), path=target)
    resample = [c for c in calls if c[0] == "sips" and "--resampleWidth" in c]
    assert resample and resample[0][:3] == ["sips", "--resampleWidth", "1728"]


def test_capture_skips_resample_on_non_retina(tmp_path):
    calls = []
    capture_screen_action(runner=_runner(calls, dpi="72.000", pixel_w="1920"),
                          path=tmp_path / "shot.png")
    assert not [c for c in calls if "--resampleWidth" in c]


def test_capture_failure_returns_guidance(tmp_path):
    out = capture_screen_action(runner=_runner([], fail_capture=True),
                                path=tmp_path / "shot.png")
    assert "실패" in out and "권한" in out


def test_capture_never_raises(tmp_path):
    def boom(cmd, capture_output=True, text=True, **kwargs):
        raise OSError("no screen")
    out = capture_screen_action(runner=boom, path=tmp_path / "shot.png")
    assert "실패" in out


def test_capture_survives_bad_sips_info(tmp_path):
    """sips 정보 조회 실패해도 캡처 경로는 반환."""
    def run(cmd, capture_output=True, text=True, **kwargs):
        if cmd[0] == "sips":
            return _Res(stdout="garbage")
        return _Res()
    target = tmp_path / "shot.png"
    out = capture_screen_action(runner=run, path=target)
    assert str(target) in out


# ---------------------------------------------------------------------------
# screen_control_action tests
# ---------------------------------------------------------------------------
from jarvis.core.control_gate import ControlGate
from jarvis.tools.jarvis_mcp import screen_control_action


def _gate(on=True):
    g = ControlGate(clock=lambda: 100.0)
    if on:
        g.enable(300.0)
    return g


def test_control_refused_when_gate_off():
    calls = []
    out = screen_control_action("click", x=10, y=20, gate=_gate(on=False),
                                runner=_runner(calls), watch=False)
    assert "화면 제어 모드" in out
    assert calls == []  # 절대 실행되지 않는다


def test_control_click_dispatch():
    calls = []
    out = screen_control_action("click", x=10, y=20, gate=_gate(),
                                runner=_runner(calls), watch=False)
    assert calls == [["cliclick", "c:10,20"]]
    assert "클릭" in out


def test_control_double_right_move_dispatch():
    for action, prefix in (("double_click", "dc"), ("right_click", "rc"), ("move", "m")):
        calls = []
        screen_control_action(action, x=5, y=7, gate=_gate(), runner=_runner(calls), watch=False)
        assert calls == [["cliclick", f"{prefix}:5,7"]]


def test_control_type_dispatch():
    calls = []
    screen_control_action("type", text="안녕 jarvis", gate=_gate(), runner=_runner(calls), watch=False)
    assert calls == [["cliclick", "t:안녕 jarvis"]]


def test_control_key_dispatch():
    calls = []
    screen_control_action("key", key="return", gate=_gate(), runner=_runner(calls), watch=False)
    assert calls == [["cliclick", "kp:return"]]


def test_control_scroll_maps_to_page_keys():
    calls = []
    screen_control_action("scroll", amount=-2, gate=_gate(), runner=_runner(calls), watch=False)
    assert calls == [["cliclick", "kp:page-down", "kp:page-down"]]
    calls.clear()
    screen_control_action("scroll", amount=3, gate=_gate(), runner=_runner(calls), watch=False)
    assert calls == [["cliclick", "kp:page-up"] + ["kp:page-up"] * 2]


def test_control_scroll_caps_repeats():
    calls = []
    screen_control_action("scroll", amount=-99, gate=_gate(), runner=_runner(calls), watch=False)
    assert len(calls[0]) == 1 + 10  # cliclick + 최대 10회


def test_control_bad_coords_guidance():
    out = screen_control_action("click", x="abc", y=None, gate=_gate(), runner=_runner([]))
    assert "좌표" in out


def test_control_unknown_action_guidance():
    out = screen_control_action("fly", gate=_gate(), runner=_runner([]))
    assert "지원하지 않는" in out


def test_control_missing_cliclick_guidance():
    def no_bin(cmd, capture_output=True, text=True):
        raise FileNotFoundError("cliclick")
    out = screen_control_action("click", x=1, y=1, gate=_gate(), runner=no_bin)
    assert "brew install cliclick" in out


def test_control_empty_type_and_key_guidance():
    assert "텍스트" in screen_control_action("type", text="", gate=_gate(), runner=_runner([]))
    assert "키" in screen_control_action("key", key="", gate=_gate(), runner=_runner([]))


def test_control_non_string_args_never_raise():
    out = screen_control_action(123, gate=_gate(), runner=_runner([]))
    assert "지원하지 않는" in out
    out = screen_control_action("key", key=7, gate=_gate(), runner=_runner([]))
    assert "키" in out
