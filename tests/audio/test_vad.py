from pathlib import Path

import numpy as np
import pytest

MODEL = Path("~/jarvis/voice_models/silero_vad.onnx").expanduser()

pytestmark = pytest.mark.skipif(not MODEL.exists(), reason="silero 모델 미설치")


def _vad():
    from jarvis.audio.vad import SileroVAD
    return SileroVAD(MODEL)


def test_silence_is_low_probability():
    vad = _vad()
    probs = [vad.prob(np.zeros(512, dtype=np.float32)) for _ in range(10)]
    assert max(probs) < 0.3


def test_reset_reproduces_first_probability():
    vad = _vad()
    rng = np.random.default_rng(0)
    frame = (rng.standard_normal(512) * 0.05).astype(np.float32)
    p1 = vad.prob(frame)
    vad.prob(frame)                 # 내부 상태가 굴러간다
    vad.reset()
    assert abs(vad.prob(frame) - p1) < 1e-6  # reset이 상태를 완전히 초기화
