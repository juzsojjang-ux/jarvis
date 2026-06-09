from voice_training import resample


def test_build_ffmpeg_resample_cmd_exact():
    cmd = resample.build_ffmpeg_resample_cmd("a.wav", "b.wav", 40000)
    assert cmd == ["ffmpeg", "-y", "-i", "a.wav", "-ar", "40000", "-ac", "1",
                   "-sample_fmt", "s16", "b.wav"]


def test_resample_file_invokes_runner(tmp_path):
    seen = {}

    def fake(cmd, check):
        seen["cmd"] = cmd

    out = resample.resample_file(tmp_path / "in.wav", tmp_path / "out.wav", runner=fake)
    assert out.endswith("out.wav")
    assert seen["cmd"][0] == "ffmpeg" and "40000" in seen["cmd"]
