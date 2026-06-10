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
        self._last_chunk_t = 0.0  # 마지막 콜백 수신 시각 — 좀비 스트림 판별용

    def subscribe(self, cb: Callable[[np.ndarray], None]) -> None:
        with self._lock:
            if cb not in self._subs:
                self._subs.append(cb)

    def unsubscribe(self, cb: Callable[[np.ndarray], None]) -> None:
        with self._lock:
            if cb in self._subs:
                self._subs.remove(cb)

    def _callback(self, indata, frames, time_info, status) -> None:
        self._last_chunk_t = time.monotonic()
        chunk = np.asarray(indata, dtype=np.float32).reshape(-1).copy()
        with self._lock:
            subs = list(self._subs)
        # 같은 객체를 모든 구독자에게 전달한다 — 구독자는 in-place 수정 금지.
        for cb in subs:
            try:
                cb(chunk)
            except Exception:  # noqa: BLE001 - 소비자 하나가 마이크를 죽이면 안 된다
                pass

    def _open(self) -> None:
        # InputStream 생성은 여기 한 곳뿐 — start/ensure_running이 장치 인자를
        # 따로 들고 있다가 한쪽만 고쳐지는 사고를 막는다.
        self._stream = sd.InputStream(
            samplerate=self.sample_rate, blocksize=self._blocksize,
            channels=1, dtype="float32", callback=self._callback,
        )
        self._stream.start()
        self._last_chunk_t = time.monotonic()  # 새 스트림 기준으로 생존 판정 리셋

    def start(self) -> None:
        self._want_running = True
        if self._stream is not None:
            return
        self._open()

    def stop(self) -> None:
        self._want_running = False
        self._retry_at = 0.0      # 백오프 잔존이 다음 세션 복구를 늦추지 않게
        self._close_stream()

    def _close_stream(self) -> None:
        # _want_running은 건드리지 않는다 — ensure_running 복구 경로가 게이트를
        # 유지한 채 스트림만 갈아끼울 수 있어야 한다.
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def ensure_running(self) -> None:
        """죽은/좀비 스트림을 2초 백오프로 재시작. macOS는 장치가 빠져도
        stream.active가 True로 남는 경우가 있어(콜백만 끊김), active 플래그가
        아니라 마지막 콜백 수신 시각으로 생존을 판정한다."""
        if not self._want_running:
            return  # start() 전/stop() 후엔 장치를 절대 열지 않는다(테스트·웨이크OFF 보호)
        alive = (self._stream is not None and self._stream.active
                 and time.monotonic() - self._last_chunk_t < 2.0)
        if alive:
            return
        now = time.monotonic()
        if now < self._retry_at:
            return
        self._retry_at = now + 2.0
        try:
            self._close_stream()
            self._open()
        except Exception:  # noqa: BLE001 - 다음 폴링에서 재시도
            self._stream = None
