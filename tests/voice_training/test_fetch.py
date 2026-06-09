from pathlib import Path

import pytest

from voice_training import fetch


def test_load_urls_ignores_comments_and_blanks(tmp_path):
    p = tmp_path / "urls.txt"
    p.write_text("# header\n\nhttps://a/1\n  https://b/2  \n# tail\n", encoding="utf-8")
    assert fetch.load_urls(p) == ["https://a/1", "https://b/2"]


def test_build_ytdlp_command_exact_flags(tmp_path):
    cmd = fetch.build_ytdlp_command("https://x/zzz", tmp_path)
    assert cmd == [
        "yt-dlp", "-x", "--audio-format", "wav", "--audio-quality", "0",
        "--no-playlist", "-o", str(tmp_path / "%(id)s.%(ext)s"), "https://x/zzz",
    ]


def test_print_share_list_lists_every_url():
    msg = fetch.print_share_list(["https://a/1", "https://b/2"])
    assert "2 URLs" in msg and "https://a/1" in msg and "https://b/2" in msg


def test_fetch_all_refuses_without_confirmation(tmp_path):
    with pytest.raises(RuntimeError):
        fetch.fetch_all(["https://a/1"], tmp_path, confirmed=False)


def test_fetch_all_runs_ytdlp_per_url_when_confirmed(tmp_path):
    calls = []

    def fake_runner(cmd, check):
        calls.append(cmd)
        out = cmd[cmd.index("-o") + 1].replace("%(id)s", "vid").replace("%(ext)s", "wav")
        Path(out).write_bytes(b"RIFF")

    out = fetch.fetch_all(["https://a/1"], tmp_path, confirmed=True, runner=fake_runner)
    assert len(calls) == 1 and calls[0][0] == "yt-dlp" and out[0].endswith(".wav")
