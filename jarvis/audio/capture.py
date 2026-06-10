# jarvis/audio/capture.py
import threading

import numpy as np


class MicCapture:
    """공유 MicStream 위의 PTT 녹음기: start()부터 stop()까지의 청크를 모아
    돌려준다. 스트림 자체는 닫지 않는다 — 웨이크 리스너가 같은 스트림을 계속
    듣는다. (이전에는 누를 때마다 InputStream을 새로 열었다.)"""

    def __init__(self, micstream):
        self._mic = micstream
        self.sample_rate = micstream.sample_rate
        self._frames: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._active = False
        micstream.subscribe(self._on_chunk)

    def _on_chunk(self, chunk: np.ndarray) -> None:
        with self._lock:
            if self._active:
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
            self._active = True
        self._mic.ensure_running()

    def stop(self) -> np.ndarray:
        with self._lock:
            self._active = False
        return self._drain()
