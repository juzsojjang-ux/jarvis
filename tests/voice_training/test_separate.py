import pytest

from voice_training import separate


class _R:
    def __init__(self, out):
        self.stdout, self.stderr = out, ""


def test_check_env_detects_coreml():
    r = _R("providers: ['CoreMLExecutionProvider', 'CPUExecutionProvider']")
    assert separate.check_env(runner=lambda *a, **k: r) is True


def test_check_env_false_when_cpu_only():
    r = _R("providers: ['CPUExecutionProvider']")
    assert separate.check_env(runner=lambda *a, **k: r) is False


def test_pick_vocal_stem_selects_vocals():
    files = ["/out/song_(Instrumental)_m.wav", "/out/song_(Vocals)_m.wav"]
    assert separate.pick_vocal_stem(files).endswith("(Vocals)_m.wav")


def test_pick_vocal_stem_raises_when_absent():
    with pytest.raises(ValueError):
        separate.pick_vocal_stem(["/out/song_(Instrumental).wav"])
