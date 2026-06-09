import io

import numpy as np
import pytest

from jarvis.tts import ipc, tts_worker


def _sine_synth(text):
    sr = 44100
    t = np.arange(int(0.1 * sr)) / sr
    return (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32), sr


def test_run_once_synthesizes_and_frames_response():
    out = io.BytesIO()
    assert tts_worker.run_once(_sine_synth, io.BytesIO(ipc.pack_request("테스트")), out) is True
    out.seek(0)
    pcm, sr = ipc.read_response(out)
    assert sr == 44100 and pcm.shape[0] == int(0.1 * 44100)


def test_run_once_eof_returns_false():
    assert tts_worker.run_once(_sine_synth, io.BytesIO(b""), io.BytesIO()) is False


def test_run_once_reports_synth_error():
    def boom(text):
        raise ValueError("nope")

    out = io.BytesIO()
    tts_worker.run_once(boom, io.BytesIO(ipc.pack_request("x")), out)
    out.seek(0)
    with pytest.raises(RuntimeError, match="nope"):
        ipc.read_response(out)
