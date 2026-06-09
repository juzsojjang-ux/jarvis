from collections.abc import Callable
from typing import Protocol


class Activator(Protocol):
    def start(self, on_press: Callable[[], None], on_release: Callable[[], None]) -> None: ...
    def stop(self) -> None: ...
