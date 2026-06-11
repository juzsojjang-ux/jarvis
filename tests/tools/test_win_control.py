from pathlib import Path
from jarvis.tools.win_control import perform, capture


class _FakeGui:
    def __init__(self): self.calls = []
    def click(self, x, y): self.calls.append(("click", x, y))
    def doubleClick(self, x, y): self.calls.append(("dbl", x, y))
    def rightClick(self, x, y): self.calls.append(("rc", x, y))
    def moveTo(self, x, y): self.calls.append(("move", x, y))
    def typewrite(self, t, interval=0): self.calls.append(("type", t))
    def press(self, k): self.calls.append(("key", k))
    def scroll(self, n): self.calls.append(("scroll", n))


def test_click_and_type_and_key_map():
    g = _FakeGui()
    assert perform("click", x=10, y=20, gui=g)
    assert perform("type", text="hi", gui=g)
    assert perform("key", key="return", gui=g)  # → enter
    assert perform("scroll", amount=-2, gui=g)
    assert ("click", 10, 20) in g.calls
    assert ("type", "hi") in g.calls
    assert ("key", "enter") in g.calls   # return → enter 매핑
    assert ("scroll", -200) in g.calls


def test_unknown_action_returns_false():
    assert perform("fly", gui=_FakeGui()) is False


def test_capture_uses_grabber(tmp_path):
    saved = []
    out = tmp_path / "shots" / "s.png"
    assert capture(out, grabber=lambda p: saved.append(p) or True)
    assert out.parent.is_dir() and saved == [out]
