from collections import deque

import numpy as np


class _Utterance(np.ndarray):
    """np.ndarray 서브클래스 — `result or prev` 패턴에서 bool 평가가 필요해
    __bool__을 True로 고정. 배열 연산은 부모 클래스에 그대로 위임한다."""

    def __new__(cls, arr: np.ndarray) -> "_Utterance":
        return np.asarray(arr, dtype=np.float32).view(cls)

    def __bool__(self) -> bool:  # `feed(...) or out` 가 ValueError 없이 동작하도록
        return True


class UtteranceDetector:
    """프레임 단위 VAD 확률을 받아 완결된 발화 PCM을 돌려주는 순수 상태기계.
    threshold 이상이면 발화 시작(직전 pre-roll 포함), silence_ms 동안 조용하면
    종료. min_speech_ms 미만은 폐기, max_s 초과는 강제 절단(긴 대화 변환 낭비
    방지). I/O 없음 — VAD/스트림과 분리해 단독 테스트한다."""

    def __init__(self, *, sample_rate: int = 16000, frame_samples: int = 512,
                 threshold: float = 0.5, silence_ms: int = 800,
                 min_speech_ms: int = 300, max_s: float = 30.0,
                 pre_roll_ms: int = 320):
        self._thr = threshold
        frame_ms = frame_samples * 1000 / sample_rate
        self._silence_frames = max(1, round(silence_ms / frame_ms))
        self._min_frames = max(1, round(min_speech_ms / frame_ms))
        self._max_frames = max(1, round(max_s * 1000 / frame_ms))
        self._pre: deque[np.ndarray] = deque(maxlen=max(1, round(pre_roll_ms / frame_ms)))
        self._buf: list[np.ndarray] = []
        self._speech_frames = 0
        self._silent = 0
        self._in_speech = False

    def reset(self) -> None:
        self._pre.clear()
        self._buf = []
        self._speech_frames = 0
        self._silent = 0
        self._in_speech = False

    def _finish(self) -> "_Utterance | None":
        buf, speech = self._buf, self._speech_frames
        self._buf = []
        self._speech_frames = 0
        self._silent = 0
        self._in_speech = False
        if speech < self._min_frames:
            return None
        return _Utterance(np.concatenate(buf))

    def feed(self, prob: float, frame: np.ndarray) -> "_Utterance | None":
        if not self._in_speech:
            self._pre.append(frame)
            if prob >= self._thr:
                self._in_speech = True
                self._buf = list(self._pre)
                self._pre.clear()
                self._speech_frames = 1
                self._silent = 0
            return None
        self._buf.append(frame)
        if prob >= self._thr:
            self._speech_frames += 1
            self._silent = 0
        else:
            self._silent += 1
        if self._silent >= self._silence_frames or len(self._buf) >= self._max_frames:
            return self._finish()
        return None
