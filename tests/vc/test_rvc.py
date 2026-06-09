import sys

import numpy as np

from jarvis.vc.rvc import RVCConversion


def test_build_command_exact():
    vc = RVCConversion("m.pth", "m.index", sample_rate=40000,
                       index_rate=0.75, f0_up=0, f0_method="rmvpe")
    assert vc._build_command("in.wav", "out.wav") == [
        "mlx-rvc", "convert", "in.wav", "out.wav",
        "--model", "m.pth", "--index", "m.index",
        "--index-rate", "0.75", "--f0-method", "rmvpe", "--pitch", "0"]


FAKE_RVC = (
    "import sys, numpy as np, soundfile as sf\n"
    "out_wav = sys.argv[3]\n"            # convert <in> <out> ...
    "sr = 40000\n"
    "t = np.arange(int(0.2 * sr)) / sr\n"
    "sf.write(out_wav, (0.1 * np.sin(2*np.pi*330*t)).astype('float32'), sr)\n"
)


def test_convert_runs_cli_and_resamples(tmp_path):
    fake = tmp_path / "fake_rvc.py"
    fake.write_text(FAKE_RVC)
    vc = RVCConversion("m.pth", "m.index", sample_rate=48000,
                       rvc_cmd=[sys.executable, str(fake)])
    out = vc.convert(np.zeros(44100, dtype=np.float32), in_rate=44100)
    assert out.dtype == np.float32
    # fake emits 0.2s @ 40000 -> resampled to 48000
    assert abs(out.shape[0] - int(0.2 * 48000)) <= 64
