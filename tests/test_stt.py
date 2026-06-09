import numpy as np

import jarvis.stt.mlx_whisper as stt_mod
from jarvis.stt.mlx_whisper import MLXWhisperSTT


def test_transcribe_passes_repo_and_language(monkeypatch):
    seen = {}

    def fake_transcribe(audio, path_or_hf_repo, language):
        seen["audio_len"] = len(audio)
        seen["repo"] = path_or_hf_repo
        seen["language"] = language
        return {"text": "  안녕하세요  "}

    monkeypatch.setattr(stt_mod.mlx_whisper, "transcribe", fake_transcribe)
    stt = MLXWhisperSTT("mlx-community/whisper-large-v3-turbo", language="ko")
    out = stt.transcribe(np.zeros(8000, dtype=np.float32))
    assert out == "안녕하세요"
    assert seen["repo"] == "mlx-community/whisper-large-v3-turbo"
    assert seen["language"] == "ko"
    assert seen["audio_len"] == 8000


def test_warm_runs_on_silence(monkeypatch):
    calls = []
    monkeypatch.setattr(
        stt_mod.mlx_whisper, "transcribe",
        lambda audio, path_or_hf_repo, language: calls.append(len(audio)) or {"text": ""},
    )
    MLXWhisperSTT("repo").warm()
    assert calls == [16000]
