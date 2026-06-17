from unittest.mock import MagicMock

from pynput import keyboard

from jarvis.activation.ask_hotkey import AskHotkey, parse_hotkey


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


# ----- AskHotkey 콤보 감지 로직(실제 키보드 없이 핸들러 직접 호출) -----

def test_fires_once_on_chord():
    hk = AskHotkey("alt+space")
    cb = MagicMock()
    hk._on_fire = cb
    hk._handle_press(keyboard.Key.alt_l)   # mod down
    hk._handle_press(keyboard.Key.space)   # main down → 발화
    hk._handle_press(keyboard.Key.space)   # 누른 채 반복 이벤트 → 재발화 금지
    cb.assert_called_once()


def test_refires_after_release():
    hk = AskHotkey("alt+space")
    cb = MagicMock()
    hk._on_fire = cb
    hk._handle_press(keyboard.Key.alt_l)
    hk._handle_press(keyboard.Key.space)
    hk._handle_release(keyboard.Key.space)  # 메인 키 릴리즈 → _fired 리셋
    hk._handle_press(keyboard.Key.space)    # 다시 누름 → 재발화
    assert cb.call_count == 2


def test_no_fire_without_mod():
    hk = AskHotkey("alt+space")
    cb = MagicMock()
    hk._on_fire = cb
    hk._handle_press(keyboard.Key.space)   # mod 없이 main만 → 발화 안 함
    cb.assert_not_called()
