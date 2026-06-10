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


# --- silero v5 입력 규격: 직전 청크 꼬리 64샘플 + 새 512샘플 = 576 ---
# 이걸 빼먹으면 에러 없이 돌지만 확률이 ~0.001로 망가져 웨이크가 전혀 안 된다
# (실측: 같은 음성에서 512만=0.001, 576=1.000). 라이브에서 실제로 났던 버그.

def _spy_inputs(vad):
    seen = []
    real_run = vad._sess.run

    def spy(outs, feeds):
        seen.append(feeds["input"].copy())
        return real_run(outs, feeds)

    vad._sess.run = spy
    return seen


def test_prob_feeds_576_sample_v5_window():
    vad = _vad()
    seen = _spy_inputs(vad)
    frame = np.full(512, 0.1, dtype=np.float32)
    vad.prob(frame)
    vad.prob(frame)
    assert all(x.shape == (1, 576) for x in seen)


def test_context_carries_previous_frame_tail():
    vad = _vad()
    seen = _spy_inputs(vad)
    f1 = np.arange(512, dtype=np.float32) / 512.0
    f2 = np.zeros(512, dtype=np.float32)
    vad.prob(f1)
    vad.prob(f2)
    assert np.allclose(seen[0][0, :64], 0.0)        # 첫 호출: 컨텍스트는 무음
    assert np.allclose(seen[1][0, :64], f1[-64:])   # 둘째 호출: 직전 꼬리 64샘플


def test_reset_clears_context():
    vad = _vad()
    seen = _spy_inputs(vad)
    vad.prob(np.full(512, 0.5, dtype=np.float32))
    vad.reset()
    vad.prob(np.zeros(512, dtype=np.float32))
    assert np.allclose(seen[1][0, :64], 0.0)        # reset 후 컨텍스트도 0
