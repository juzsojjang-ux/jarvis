import threading

import numpy as np
import sounddevice as sd


class RingBuffer:
    """Thread-safe mono float32 FIFO. read() pads with zeros (silence) on underrun."""

    def __init__(self):
        self._buf = np.zeros(0, dtype=np.float32)
        self._lock = threading.Lock()

    def write(self, pcm: np.ndarray) -> None:
        pcm = np.asarray(pcm, dtype=np.float32)
        with self._lock:
            self._buf = np.concatenate([self._buf, pcm])

    def read(self, n: int) -> np.ndarray:
        with self._lock:
            out = self._buf[:n]
            self._buf = self._buf[len(out):]
        if len(out) < n:
            out = np.concatenate([out, np.zeros(n - len(out), dtype=np.float32)])
        return out

    def clear(self) -> None:
        with self._lock:
            self._buf = np.zeros(0, dtype=np.float32)

    def pending(self) -> int:
        with self._lock:
            return len(self._buf)


class Playback:
    """OutputStream at the playback rate, fed from a ring buffer in the PortAudio
    callback. Barge-in = clear ring + OutputStream.abort(), then re-open (sd.stop()
    does NOT work on a user OutputStream)."""

    def __init__(self, sample_rate: int = 48000):
        self.sample_rate = sample_rate
        self._ring = RingBuffer()
        self._stream: sd.OutputStream | None = None

    def _callback(self, outdata, frames, time_info, status) -> None:
        outdata[:, 0] = self._ring.read(frames)

    def _open(self) -> None:
        self._stream = sd.OutputStream(
            samplerate=self.sample_rate, channels=1, dtype="float32", callback=self._callback
        )
        self._stream.start()

    def start(self) -> None:
        if self._stream is None:
            self._open()

    def feed(self, pcm: np.ndarray) -> None:
        self._ring.write(pcm)

    def pending(self) -> int:
        """Samples still queued for playback (0 = finished) — lets the orchestrator hold
        the SPEAKING state/subtitle until the audio actually ends."""
        return self._ring.pending()

    def abort(self) -> None:
        self._ring.clear()
        if self._stream is not None:
            self._stream.abort()
            self._stream.close()
            self._stream = None
        self._open()

    def close(self) -> None:
        if self._stream is not None:
            self._stream.abort()
            self._stream.close()
            self._stream = None
