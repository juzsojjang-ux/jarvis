"""Ask 입력창 전역 단축키 — pynput 콤보(수식키+키) 감지. PTT(ptt.py)와 같은 입력
모니터링 권한을 쓰며 별도 Listener로 공존한다. 파서는 순수 함수라 테스트 가능."""
from __future__ import annotations

from collections.abc import Callable

from pynput import keyboard

# 토큰 → pynput 키 집합(좌우 모두 허용). 한 토큰이 여러 실제 키에 대응.
_MODS: dict[str, set] = {
    "alt": {keyboard.Key.alt_l, keyboard.Key.alt_r, keyboard.Key.alt_gr},
    "option": {keyboard.Key.alt_l, keyboard.Key.alt_r, keyboard.Key.alt_gr},
    "ctrl": {keyboard.Key.ctrl_l, keyboard.Key.ctrl_r},
    "control": {keyboard.Key.ctrl_l, keyboard.Key.ctrl_r},
    "shift": {keyboard.Key.shift_l, keyboard.Key.shift_r},
    "cmd": {keyboard.Key.cmd, keyboard.Key.cmd_r},
    "win": {keyboard.Key.cmd, keyboard.Key.cmd_r},
}
_NAMED = {"space": keyboard.Key.space, "enter": keyboard.Key.enter,
          "tab": keyboard.Key.tab}
_DEFAULT = "alt+space"


def parse_hotkey(spec: str) -> tuple[set, "keyboard.Key | keyboard.KeyCode"]:
    """'alt+space' → (수식키 집합, 메인 키). 파싱 실패 시 기본(alt+space)로 폴백."""
    tokens = [t.strip().lower() for t in (spec or "").split("+") if t.strip()]
    mods: set = set()
    main = None
    for tok in tokens:
        if tok in _MODS:
            mods |= _MODS[tok]
        elif tok in _NAMED:
            main = _NAMED[tok]
        elif len(tok) == 1:
            main = keyboard.KeyCode.from_char(tok)
        # 모르는 토큰은 무시
    if main is None or not mods:
        if spec == _DEFAULT:  # 무한 재귀 방지
            mods = _MODS["alt"]
            return mods, keyboard.Key.space
        return parse_hotkey(_DEFAULT)
    return mods, main


class AskHotkey:
    """설정된 콤보가 눌리는 순간 on_fire()를 1회 호출(누른 채 유지해도 1회). PTT와
    별개 Listener로 돌며, 키 감지가 실패해도 음성 기능에 영향 주지 않는다."""

    def __init__(self, spec: str = _DEFAULT):
        self._mods, self._main = parse_hotkey(spec)
        self._on_fire: Callable[[], None] | None = None
        self._listener: keyboard.Listener | None = None
        self._pressed: set = set()
        self._fired = False

    def start(self, on_fire: Callable[[], None]) -> None:
        self.stop()  # 중복 start 시 기존 리스너 누수 방지
        self._on_fire = on_fire
        self._listener = keyboard.Listener(
            on_press=self._handle_press, on_release=self._handle_release)
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    def _handle_press(self, key) -> None:
        # 순서: mod 먼저, main 나중에 눌러야 발화한다(역순은 의도적으로 무시 — 전역
        # 단축키 관례). 메인 키를 떼기 전까지 _fired 래치로 단 1회만 발화.
        self._pressed.add(key)
        mod_ok = any(m in self._pressed for m in self._mods)
        if mod_ok and key == self._main and not self._fired:
            self._fired = True
            if self._on_fire:
                try:
                    self._on_fire()
                except Exception:  # noqa: BLE001 - 콜백 오류가 리스너를 죽이면 안 된다
                    pass

    def _handle_release(self, key) -> None:
        self._pressed.discard(key)
        if key == self._main:
            self._fired = False  # 메인 키를 떼면 재발화 허용
