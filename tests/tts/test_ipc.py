import io

import numpy as np
import pytest

from jarvis.tts import ipc


def test_request_roundtrip():
    assert ipc.read_request(io.BytesIO(ipc.pack_request("안녕하세요"))) == "안녕하세요"


def test_request_eof_returns_none():
    assert ipc.read_request(io.BytesIO(b"")) is None


def test_response_roundtrip_pcm():
    pcm = np.linspace(-1, 1, 2048, dtype=np.float32)
    out, sr = ipc.read_response(io.BytesIO(ipc.pack_response(pcm, 44100)))
    assert sr == 44100 and out.dtype == np.float32 and out.shape == pcm.shape
    np.testing.assert_allclose(out, pcm, atol=1e-6)


def test_error_response_raises():
    with pytest.raises(RuntimeError, match="boom"):
        ipc.read_response(io.BytesIO(ipc.pack_error("boom")))
