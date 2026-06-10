import threading

import numpy as np
import sounddevice as sd


class MicCapture:
    """Captures 16 kHz mono float32 PCM while held. Frames appended in the PortAudio
    callback thread; concatenated on stop()."""

    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self._frames: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()

    def _callback(self, indata, frames, time_info, status) -> None:
        chunk = np.asarray(indata, dtype=np.float32).reshape(-1).copy()
        with self._lock:
            self._frames.append(chunk)

    def _drain(self) -> np.ndarray:
        with self._lock:
            frames = self._frames
            self._frames = []
        if not frames:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(frames).astype(np.float32)

    def level_tail(self, window: int = 1600) -> np.ndarray:
        """Peek (no drain) the most recent ~window samples — for the HUD live meter."""
        with self._lock:
            if not self._frames:
                return np.zeros(0, dtype=np.float32)
            tail = np.concatenate(self._frames[-4:])
        return tail[-window:]

    def start(self) -> None:
        with self._lock:
            self._frames = []
        self._stream = sd.InputStream(
            samplerate=self.sample_rate, channels=1, dtype="float32", callback=self._callback
        )
        self._stream.start()

    def stop(self) -> np.ndarray:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        return self._drain()
