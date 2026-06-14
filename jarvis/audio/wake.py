from __future__ import annotations

import asyncio
import os
import threading
from collections import deque
from collections.abc import Callable
from pathlib import Path

import numpy as np

_PUNCT = " \t,.!?~…·-—\"'""'';:"
_EMPTY = np.zeros(0, dtype=np.float32)  # 30ms 폴링마다 빈 배열을 새로 만들지 않는다


def _rest_after_collapsed(t: str, wl: str) -> str:
    """공백 무시 매칭에서 t 앞부분 wl(공백 없는 길이)만큼 소비하고 나머지를 돌려준다.
    STT가 "자 비스 켜줘"처럼 끊어도 명령부("켜줘")를 정확히 뽑는다."""
    i = consumed = 0
    while i < len(t) and consumed < len(wl):
        if t[i] != " ":
            consumed += 1
        i += 1
    return t[i:]


def match_wake(text: str, wake_words: list[str]) -> tuple[bool, str]:
    """변환 텍스트가 웨이크워드로 '시작'하는지 판정하고 명령부를 돌려준다.
    (True, 명령) / (False, ""). 문장 중간 언급은 호출이 아니다.
    공백 무시 매칭으로 STT가 "자 비스"처럼 끊어 적어도 인식한다."""
    t = text.strip().lower().lstrip(_PUNCT)
    tc = t.replace(" ", "")
    for w in wake_words:
        wl = w.lower().replace(" ", "")
        if not wl:
            continue
        if t.startswith(wl):
            rest = t[len(wl):]
        elif tc.startswith(wl):           # 공백 끊김("자 비스") 허용
            rest = _rest_after_collapsed(t, wl)
        else:
            continue
        # 직접 붙은 호격("자비스야")만 제거 — 뒤 단어의 첫 글자('아침')는 보존.
        if rest[:1] in ("야", "아") and (len(rest) <= 1 or rest[1] in _PUNCT):
            rest = rest[1:]
        return True, rest.lstrip(_PUNCT).strip()
    return False, ""


class WakeListener:
    """상시 웨이크 경로: MicStream 청크 -> 512샘플 윈도우 VAD -> UtteranceDetector
    -> on_utterance(pcm). gate()가 False(IDLE 아님/에코 쿨다운)면 부분 버퍼를
    버린다 — 자비스 자신의 목소리나 PTT 녹음을 발화로 오인하지 않기 위해서다."""

    # 이보다 작은 피크는 확실한 무음 — ONNX 호출을 건너뛴다(대기 배터리 절감).
    # silero가 진짜 무음에 주는 확률(~0.001)보다 훨씬 보수적인 문턱.
    _SILENCE_PEAK = 0.003

    def __init__(self, micstream, vad, detector, *, window: int = 512,
                 poll_s: float = 0.03):
        self._mic = micstream
        self._vad = vad
        self._det = detector
        self._window = window
        self._poll_s = poll_s
        self._pending: deque[np.ndarray] = deque()
        self._lock = threading.Lock()
        self._carry = _EMPTY
        self._task: asyncio.Task | None = None
        # JARVIS_WAKE_DEBUG=1: 레이어별 계측(청크 유입/피크/VAD 확률) — 현장 튜닝용.
        self._debug = os.environ.get("JARVIS_WAKE_DEBUG", "") == "1"
        self._dbg = {"polls": 0, "open": 0, "frames": 0, "onnx": 0, "peak": 0.0, "pmax": 0.0}

    def _on_chunk(self, chunk: np.ndarray) -> None:  # PortAudio 콜백 스레드
        with self._lock:
            self._pending.append(chunk)

    def start(self, on_utterance: Callable[[np.ndarray], None],
              gate: Callable[[], bool]) -> None:
        if self._task is not None and not self._task.done():
            return  # 이미 듣는 중 — 중복 구독/고아 태스크 방지
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
                return _EMPTY
            if len(self._pending) == 1:
                chunk = self._pending.popleft()
                return chunk
            chunks = list(self._pending)
            self._pending.clear()
        return np.concatenate(chunks)

    def _reset(self) -> None:
        with self._lock:
            self._pending.clear()
        self._carry = _EMPTY
        self._det.reset()
        self._vad.reset()

    def _process(self) -> list[np.ndarray]:
        drained = self._drain_pending()
        if len(drained) == 0 and len(self._carry) == 0:
            return []
        data = drained if len(self._carry) == 0 else np.concatenate([self._carry, drained])
        n = (len(data) // self._window) * self._window
        self._carry = data[n:]
        out: list[np.ndarray] = []
        for i in range(0, n, self._window):
            frame = data[i:i + self._window]
            peak = float(np.max(np.abs(frame)))
            # 무음 프레임은 ONNX를 태우지 않는다 — 발화 중엔 은닉상태 연속성을
            # 위해 항상 실측한다.
            if not self._det.in_speech and peak < self._SILENCE_PEAK:
                prob = 0.0
            else:
                prob = self._vad.prob(frame)
                if self._debug:
                    self._dbg["onnx"] += 1
                    self._dbg["pmax"] = max(self._dbg["pmax"], prob)
            if self._debug:
                self._dbg["frames"] += 1
                self._dbg["peak"] = max(self._dbg["peak"], peak)
            utt = self._det.feed(prob, frame)
            if utt is not None:
                out.append(utt)
        return out

    async def _loop(self) -> None:
        try:
            while True:
                self._mic.ensure_running()
                gate_open = bool(self._gate())
                if not gate_open:
                    # 닫힘 동안 들은 것은 전부 버린다(에코·PTT 오인 방지).
                    # _reset은 멱등·저비용이라 매 폴마다 불러도 된다.
                    self._reset()
                else:
                    try:
                        utts = self._process()
                    except Exception as exc:  # noqa: BLE001 - VAD 한 번의 오류로 영구 먹통 금지
                        print(f"[웨이크워드] 처리 오류(루프 유지): {exc}")
                        self._reset()
                        utts = []
                    for utt in utts:
                        if self._debug:
                            print(f"[wake-dbg] 발화 감지: {len(utt)}샘플 ({len(utt)/16000:.1f}s)")
                        try:
                            self._on_utterance(utt)
                        except Exception as exc:  # noqa: BLE001 - 루프는 죽지 않는다
                            print(f"[웨이크워드] on_utterance 오류(루프 유지): {exc}")
                if self._debug:
                    d = self._dbg
                    d["polls"] += 1
                    d["open"] += 1 if gate_open else 0
                    if d["polls"] % 66 == 0:  # ~2초마다 요약
                        print(f"[wake-dbg] open={d['open']}/66 frames={d['frames']} "
                              f"onnx={d['onnx']} peak={d['peak']:.4f} pmax={d['pmax']:.3f} "
                              f"in_speech={self._det.in_speech}")
                        d.update(open=0, frames=0, onnx=0, peak=0.0, pmax=0.0)
                await asyncio.sleep(self._poll_s)
        except asyncio.CancelledError:
            pass


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
        min_speech_ms=settings.wake_min_speech_ms,
        max_s=settings.wake_max_utterance_s,
        pre_roll_ms=settings.wake_pre_roll_ms,
    )
    # 윈도우 크기의 단일 출처는 VAD 모델(silero v5 = 512@16k)이다.
    return WakeListener(micstream, vad, detector, window=SileroVAD.WINDOW)
