from __future__ import annotations

import threading
import time
from collections.abc import Callable

import numpy as np
import sounddevice as sd


class MicStream:
    """상시 16 kHz 모노 입력 스트림 하나를 모든 소비자(PTT 캡처, 웨이크 리스너)가
    공유한다 — 같은 장치에 스트림 2개를 여는 낭비/충돌 방지. blocksize=512는
    silero VAD 윈도우와 일치. 구독자는 PortAudio 콜백 스레드에서 불리므로
    append 수준으로 가벼워야 한다.
    start/stop/ensure_running은 단일 호출자(오케스트레이터 asyncio 루프) 가정 —
    잠금 없이 _stream을 만지므로 다중 호출자 금지.
    ensure_running()은 start() 호출 이후 ~ stop() 호출 이전 구간에서만 장치를
    여닫는다. start() 전 또는 stop() 후엔 아무것도 하지 않는다(테스트·웨이크OFF 보호)."""

    def __init__(self, sample_rate: int = 16000, blocksize: int = 512):
        self.sample_rate = sample_rate
        self._blocksize = blocksize
        self._subs: list[Callable[[np.ndarray], None]] = []
        self._lock = threading.Lock()
        self._stream: sd.InputStream | None = None
        self._retry_at = 0.0
        self._want_running = False

    def subscribe(self, cb: Callable[[np.ndarray], None]) -> None:
        with self._lock:
            if cb not in self._subs:
                self._subs.append(cb)

    def unsubscribe(self, cb: Callable[[np.ndarray], None]) -> None:
        with self._lock:
            if cb in self._subs:
                self._subs.remove(cb)

    def _callback(self, indata, frames, time_info, status) -> None:
        chunk = np.asarray(indata, dtype=np.float32).reshape(-1).copy()
        with self._lock:
            subs = list(self._subs)
        # 같은 객체를 모든 구독자에게 전달한다 — 구독자는 in-place 수정 금지.
        for cb in subs:
            try:
                cb(chunk)
            except Exception:  # noqa: BLE001 - 소비자 하나가 마이크를 죽이면 안 된다
                pass

    def start(self) -> None:
        self._want_running = True
        if self._stream is not None:
            return
        self._stream = sd.InputStream(
            samplerate=self.sample_rate, blocksize=self._blocksize,
            channels=1, dtype="float32", callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> None:
        self._want_running = False
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def ensure_running(self) -> None:
        """장치 변경(이어폰 연결 등)으로 죽은 스트림을 2초 백오프로 재시작."""
        if not self._want_running:
            return  # start() 전/stop() 후엔 장치를 절대 열지 않는다(테스트·웨이크OFF 보호)
        if self._stream is not None and self._stream.active:
            return
        now = time.monotonic()
        if now < self._retry_at:
            return
        self._retry_at = now + 2.0
        try:
            self.stop()
            self.start()
        except Exception:  # noqa: BLE001 - 다음 폴링에서 재시도
            self._stream = None
