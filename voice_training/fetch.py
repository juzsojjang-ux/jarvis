"""Fetch JARVIS reference audio from a curated URL list using yt-dlp.

COPYRIGHT / PRIVACY POLICY (read before running):
  - Personal, local, on-device voice-model training ONLY. No redistribution
    of downloaded audio or the resulting model.
  - You MUST review and approve the URL list (share-list-before-bulk):
    print print_share_list(urls) and pass confirmed=True only after a human
    has eyeballed it.
  - Raw downloads are auto-deleted after the dataset is built (delete_raws()).
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def load_urls(path) -> list[str]:
    urls: list[str] = []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        urls.append(line)
    return urls


def build_ytdlp_command(url: str, out_dir) -> list[str]:
    out_tmpl = str(Path(out_dir) / "%(id)s.%(ext)s")
    return ["yt-dlp", "-x", "--audio-format", "wav", "--audio-quality", "0",
            "--no-playlist", "-o", out_tmpl, url]


def print_share_list(urls: list[str]) -> str:
    lines = ["SHARE THIS URL LIST FOR APPROVAL BEFORE BULK DOWNLOAD:",
             f"  ({len(urls)} URLs, personal/local training only, no redistribution)"]
    for i, u in enumerate(urls, 1):
        lines.append(f"  {i:>3}. {u}")
    return "\n".join(lines)


def fetch_all(urls, out_dir, confirmed: bool, runner=subprocess.run) -> list[str]:
    if not confirmed:
        raise RuntimeError(
            "Refusing bulk download: review print_share_list(urls) and pass "
            "confirmed=True only after the URL list is approved.")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for url in urls:
        runner(build_ytdlp_command(url, out), check=True)
    return [str(w) for w in sorted(out.glob("*.wav"))]


def delete_raws(out_dir) -> None:
    raw = Path(out_dir)
    if raw.exists():
        shutil.rmtree(raw)
