import numpy as np

from jarvis.audio.utterance import UtteranceDetector

FRAME = 512  # 32 ms @16 kHz


def _frames(n, value=0.1):
    return [np.full(FRAME, value, dtype=np.float32) for _ in range(n)]


def _det(**kw):
    # silence_ms=96(3프레임), min_speech_ms=64(2프레임)로 줄여 테스트를 짧게.
    defaults = dict(threshold=0.5, silence_ms=96, min_speech_ms=64, max_s=30.0,
                    pre_roll_ms=64)
    defaults.update(kw)
    return UtteranceDetector(**defaults)


def test_utterance_completes_after_silence():
    det = _det()
    out = None
    for f in _frames(5):                      # 말소리 5프레임
        assert det.feed(0.9, f) is None
    for f in _frames(3):                      # 침묵 3프레임 -> 발화 종료
        r = det.feed(0.1, f)
        if r is not None:
            out = r
    assert out is not None
    assert out.dtype == np.float32 and out.ndim == 1
    # pre-roll(최대 2프레임) + 말소리 5 + 침묵 꼬리 일부가 포함된다
    assert len(out) >= 5 * FRAME


def test_too_short_speech_is_dropped():
    det = _det()
    det.feed(0.9, _frames(1)[0])              # 말소리 1프레임 < min 2프레임
    out = None
    for f in _frames(3):
        r = det.feed(0.1, f)
        if r is not None:
            out = r
    assert out is None


def test_pre_roll_is_included():
    det = _det()
    pre = np.full(FRAME, 0.7, dtype=np.float32)
    det.feed(0.1, pre)                        # 발화 직전 프레임(pre-roll에 저장)
    for f in _frames(4):
        det.feed(0.9, f)
    out = None
    for f in _frames(3, value=0.0):
        r = det.feed(0.1, f)
        if r is not None:
            out = r
    assert out is not None
    assert np.allclose(out[:FRAME], 0.7)      # 첫 프레임 = pre-roll


def test_max_length_force_cuts():
    det = _det(max_s=0.2)                     # 0.2초 = 6.25 -> 7프레임 캡
    out = None
    for f in _frames(20):
        r = det.feed(0.9, f)                  # 침묵 없이도 캡에서 잘려 나온다
        if r is not None:
            out = r
    assert out is not None


def test_reset_clears_partial_buffer():
    det = _det()
    for f in _frames(4):
        det.feed(0.9, f)
    det.reset()                               # PTT/SPEAKING이 끼어든 상황
    out = None
    for f in _frames(3):
        r = det.feed(0.1, f)
        if r is not None:
            out = r
    assert out is None


def test_second_utterance_after_natural_completion():
    det = _det()
    for f in _frames(5):
        det.feed(0.9, f)
    out1 = None
    for f in _frames(3):
        r = det.feed(0.1, f)
        if r is not None:
            out1 = r
    assert out1 is not None

    # 두 번째 발화: reset() 없이도 깨끗한 상태에서 다시 감지되어야 한다
    for f in _frames(5):
        det.feed(0.9, f)
    out2 = None
    for f in _frames(3):
        r = det.feed(0.1, f)
        if r is not None:
            out2 = r
    assert out2 is not None
