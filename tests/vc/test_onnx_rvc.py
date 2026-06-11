import numpy as np
from jarvis.vc.onnx_rvc import OnnxRVCConversion, _Dio


class _In:
    def __init__(self, name): self.name = name


class _FakeSession:
    """vec: returns (1, T, 768). syn: returns (1, 1, N) waveform-ish."""
    def __init__(self, path):
        self.path = path
        self.kind = "vec" if "vec" in path else "syn"
    def get_inputs(self):
        if self.kind == "vec":
            return [_In("source")]
        return [_In(n) for n in ("phone", "phone_lengths", "pitch", "pitchf", "ds", "rnd")]
    def run(self, _outs, feed):
        if self.kind == "vec":
            # 입력 길이에 비례한 T로 (1, T, 768)
            src = list(feed.values())[0]
            T = max(2, src.shape[-1] // 320)
            return [np.random.rand(1, T, 768).astype(np.float32)]
        # syn: hub로부터 길이 추정해 파형 반환
        hub = list(feed.values())[0]
        n = hub.shape[2] * 320
        return [np.random.rand(1, 1, n).astype(np.float32) * 0.1]


def _conv(**kw):
    return OnnxRVCConversion("voice_models/jarvis.onnx", "voice_models/vec-768-layer-12.onnx",
                             session_factory=lambda p: _FakeSession(p), **kw)


def test_convert_returns_float32_mono():
    c = _conv()
    out = c.convert((np.random.rand(40000).astype(np.float32) - 0.5) * 0.2, 40000)
    assert out.dtype == np.float32 and out.ndim == 1 and len(out) > 0


def test_short_input_returns_as_is():
    c = _conv()
    tiny = np.zeros(100, dtype=np.float32)
    assert len(c.convert(tiny, 40000)) == len(tiny)


def test_resamples_non_40k_input():
    c = _conv()
    out = c.convert((np.random.rand(24000).astype(np.float32) - 0.5) * 0.2, 24000)
    assert out.dtype == np.float32 and len(out) > 0


def test_dio_compute_f0_shape():
    d = _Dio()
    wav = (np.random.rand(40000) - 0.5) * 0.2
    f0 = d.compute_f0(wav, 100)
    assert len(f0) == 100
