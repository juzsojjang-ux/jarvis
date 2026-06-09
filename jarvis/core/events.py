import enum
from dataclasses import dataclass


class State(enum.Enum):
    IDLE = enum.auto()
    CAPTURING = enum.auto()
    TRANSCRIBING = enum.auto()
    THINKING = enum.auto()
    SPEAKING = enum.auto()


@dataclass(frozen=True)
class Transcript:
    text: str


@dataclass(frozen=True)
class SpeechChunk:
    text: str


@dataclass(frozen=True)
class StateChanged:
    state: State
