import threading

import numpy as np
import sounddevice as sd


class RingBuffer:
    """Thread-safe mono float32 FIFO. read() pads with zeros (silence) on underrun."""

    # 상한: 스트림이 멈춘(또는 못 연) 상태에서 feed가 계속 쌓이면 메모리가 무한 증가한다.
    # 60초(48k 기준)를 넘으면 가장 오래된 샘플을 드롭 — 재생 큐가 폭주하지 않게.
    _MAX_SAMPLES = 48000 * 60

    def __init__(self):
        self._buf = np.zeros(0, dtype=np.float32)
        self._lock = threading.Lock()

    def write(self, pcm: np.ndarray) -> None:
        pcm = np.asarray(pcm, dtype=np.float32)
        with self._lock:
            buf = np.concatenate([self._buf, pcm])
            if len(buf) > self._MAX_SAMPLES:
                buf = buf[-self._MAX_SAMPLES:]   # 오래된 것 드롭(무한 증가 방지)
            self._buf = buf

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
        st = sd.OutputStream(
            samplerate=self.sample_rate, channels=1, dtype="float32", callback=self._callback
        )
        try:
            st.start()
        except Exception:
            try:
                st.close()      # 부분 생성 정리(누수 방지)
            except Exception:  # noqa: BLE001
                pass
            raise
        self._stream = st

    def _ensure_open(self) -> None:
        """스트림이 없으면 연다. 실패해도 예외를 삼켜 _stream=None을 유지 → 다음 feed/start에서
        재시도한다. (audit high #3: abort의 _open 예외가 전파되고 _stream이 영구 None으로 남아
        바지인 한 번에 세션 내내 음성이 멎던 것을 방지 — MicStream의 자가복구 패턴 차용.)"""
        if self._stream is not None:
            return
        try:
            self._open()
        except Exception:  # noqa: BLE001 - 기기 전환/샘플레이트 미지원 등 → 다음에 재시도
            self._stream = None

    def start(self) -> None:
        self._ensure_open()

    def feed(self, pcm: np.ndarray) -> None:
        self._ensure_open()      # abort가 재오픈에 실패했어도 여기서 lazy 재시도 → 침묵 복구
        self._ring.write(pcm)

    def pending(self) -> int:
        """Samples still queued for playback (0 = finished) — lets the orchestrator hold
        the SPEAKING state/subtitle until the audio actually ends."""
        return self._ring.pending()

    def abort(self) -> None:
        # 바지인 시 fire-and-forget로 호출되므로 절대 예외를 올리면 안 된다(조용히 죽음 방지).
        self._ring.clear()
        if self._stream is not None:
            try:
                self._stream.abort()
                self._stream.close()
            except Exception:  # noqa: BLE001
                pass
            self._stream = None
        self._ensure_open()      # 실패해도 예외 없음 → 다음 feed에서 재시도

    def close(self) -> None:
        if self._stream is not None:
            try:
                self._stream.abort()
                self._stream.close()
            except Exception:  # noqa: BLE001
                pass
            self._stream = None
