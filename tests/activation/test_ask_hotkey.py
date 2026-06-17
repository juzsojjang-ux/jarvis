from pynput import keyboard

from jarvis.activation.ask_hotkey import parse_hotkey


def test_parse_modifier_plus_space():
    mods, main = parse_hotkey("alt+space")
    assert keyboard.Key.alt_l in mods and keyboard.Key.alt_r in mods
    assert main == keyboard.Key.space


def test_parse_ctrl_letter():
    mods, main = parse_hotkey("ctrl+j")
    assert keyboard.Key.ctrl_l in mods
    assert main == keyboard.KeyCode.from_char("j")


def test_parse_invalid_falls_back_to_default():
    # 빈 문자열·쓰레기 → 기본(alt+space)
    assert parse_hotkey("") == parse_hotkey("alt+space")
    assert parse_hotkey("???") == parse_hotkey("alt+space")
