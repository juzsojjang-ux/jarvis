from __future__ import annotations

import asyncio
import contextlib
import threading
from collections import deque
from collections.abc import Callable
from pathlib import Path

import numpy as np

_PUNCT = " \t,.!?~…·-—\"'""'';:"


def match_wake(text: str, wake_words: list[str]) -> tuple[bool, str]:
    """변환 텍스트가 웨이크워드로 '시작'하는지 판정하고 명령부를 돌려준다.
    (True, 명령) / (False, ""). 문장 중간 언급은 호출이 아니다."""
    t = text.strip().lower().lstrip(_PUNCT)
    for w in wake_words:
        wl = w.lower()
        if not t.startswith(wl):
            continue
        rest = t[len(wl):]
        # 직접 붙은 호격("자비스야")만 제거 — 뒤 단어의 첫 글자('아침')는 보존.
        if rest[:1] in ("야", "아") and (len(rest) <= 1 or rest[1] in _PUNCT):
            rest = rest[1:]
        return True, rest.lstrip(_PUNCT).strip()
    return False, ""


class WakeListener:
    """상시 웨이크 경로: MicStream 청크 -> 512샘플 윈도우 VAD -> UtteranceDetector
    -> on_utterance(pcm). gate()가 False(IDLE 아님/에코 쿨다운)면 부분 버퍼를
    버린다 — 자비스 자신의 목소리나 PTT 녹음을 발화로 오인하지 않기 위해서다."""

    def __init__(self, micstream, vad, detector, *, window: int = 512,
                 poll_s: float = 0.03):
        self._mic = micstream
        self._vad = vad
        self._det = detector
        self._window = window
        self._poll_s = poll_s
        self._pending: deque[np.ndarray] = deque()
        self._lock = threading.Lock()
        self._carry = np.zeros(0, dtype=np.float32)
        self._task: asyncio.Task | None = None
        self._was_open = False

    def _on_chunk(self, chunk: np.ndarray) -> None:  # PortAudio 콜백 스레드
        with self._lock:
            self._pending.append(chunk)

    def start(self, on_utterance: Callable[[np.ndarray], None],
              gate: Callable[[], bool]) -> None:
        self._on_utterance = on_utterance
        self._gate = gate
        self._mic.subscribe(self._on_chunk)
        self._task = asyncio.create_task(self._loop())

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None
        self._mic.unsubscribe(self._on_chunk)

    def _drain_pending(self) -> np.ndarray:
        with self._lock:
            if not self._pending:
                return np.zeros(0, dtype=np.float32)
            chunks = list(self._pending)
            self._pending.clear()
        return np.concatenate(chunks)

    def _reset(self) -> None:
        with self._lock:
            self._pending.clear()
        self._carry = np.zeros(0, dtype=np.float32)
        self._det.reset()
        self._vad.reset()

    def _process(self) -> list[np.ndarray]:
        data = np.concatenate([self._carry, self._drain_pending()])
        n = (len(data) // self._window) * self._window
        self._carry = data[n:]
        out: list[np.ndarray] = []
        for i in range(0, n, self._window):
            frame = data[i:i + self._window]
            utt = self._det.feed(self._vad.prob(frame), frame)
            if utt is not None:
                out.append(utt)
        return out

    async def _loop(self) -> None:
        with contextlib.suppress(asyncio.CancelledError):
            while True:
                self._mic.ensure_running()
                if not self._gate():
                    if self._was_open:
                        self._reset()          # 전환: 상태기계·버퍼 전체 초기화
                    else:
                        self._drain_pending()  # 지속 닫힘: 새 오디오만 버린다
                        self._carry = np.zeros(0, dtype=np.float32)
                    self._was_open = False
                else:
                    self._was_open = True
                    for utt in self._process():
                        self._on_utterance(utt)
                await asyncio.sleep(self._poll_s)


def build_wake(settings, micstream) -> WakeListener | None:
    """설정으로 웨이크 경로를 조립한다. 모델 다운로드/로드 실패 시 None을 돌려
    웨이크만 끄고 나머지(PTT)는 정상 가동한다."""
    from .utterance import UtteranceDetector
    from .vad import SileroVAD, ensure_silero_model

    try:
        model = ensure_silero_model(Path(settings.vad_model_path))
        vad = SileroVAD(model)
    except Exception as exc:  # noqa: BLE001 - 웨이크는 옵션, 부팅은 계속
        print(f"[웨이크워드] 비활성화(VAD 준비 실패): {exc}")
        return None
    detector = UtteranceDetector(
        threshold=settings.wake_vad_threshold,
        silence_ms=settings.wake_silence_ms,
        max_s=settings.wake_max_utterance_s,
    )
    return WakeListener(micstream, vad, detector)
