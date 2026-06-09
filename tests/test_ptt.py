from pynput import keyboard

from jarvis.activation.ptt import PushToTalk


def test_press_release_dispatch_and_dedup():
    calls = []
    ptt = PushToTalk("alt_r")
    ptt._on_press = lambda: calls.append("press")
    ptt._on_release = lambda: calls.append("release")

    ptt._handle_press(keyboard.Key.alt_r)
    ptt._handle_press(keyboard.Key.alt_r)  # held -> no duplicate press
    ptt._handle_release(keyboard.Key.alt_r)
    assert calls == ["press", "release"]


def test_other_keys_ignored():
    calls = []
    ptt = PushToTalk("alt_r")
    ptt._on_press = lambda: calls.append("press")
    ptt._on_release = lambda: calls.append("release")
    ptt._handle_press(keyboard.Key.space)
    ptt._handle_release(keyboard.Key.space)
    assert calls == []
