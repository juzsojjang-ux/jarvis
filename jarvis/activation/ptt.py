from collections.abc import Callable

from pynput import keyboard


class PushToTalk:
    """Right-Option push-to-talk via a raw keyboard.Listener (NOT GlobalHotKeys)."""

    def __init__(self, key_name: str = "alt_r"):
        # 알 수 없는 키 이름이 와도 죽지 않고 기본(오른쪽 Alt)으로 폴백한다.
        self._key = getattr(keyboard.Key, key_name, None) or keyboard.Key.alt_r
        self._listener: keyboard.Listener | None = None
        self._on_press: Callable[[], None] | None = None
        self._on_release: Callable[[], None] | None = None
        self._held = False

    def start(self, on_press: Callable[[], None], on_release: Callable[[], None]) -> None:
        self._on_press = on_press
        self._on_release = on_release
        self._listener = keyboard.Listener(
            on_press=self._handle_press, on_release=self._handle_release
        )
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    def _handle_press(self, key) -> None:
        if key == self._key and not self._held:
            self._held = True
            if self._on_press:
                self._on_press()

    def _handle_release(self, key) -> None:
        if key == self._key and self._held:
            self._held = False
            if self._on_release:
                self._on_release()
