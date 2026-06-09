#!/usr/bin/env python3
"""Adapter shim: JARVIS's stable convert-contract -> the .venv-rvc RVC runtime.

Runs INSIDE .venv-rvc ONLY (never imported by the main venv). RVCConversion in the
main venv shells out to:

    <.venv-rvc python> rvc_infer_cli.py convert <in.wav> <out.wav> \
        --model <jarvis.pth> [--index <added_*.index>] \
        --index-rate <r> --f0-method <m> --pitch <p>

This file is the ONLY runtime-specific piece. Default runtime: rvc-python
(`python -m rvc_python cli`, installed by voice_training/setup_rvc.sh). To swap to a
different RVC runtime (the Apple-Silicon fork, mlx-rvc, ...) edit ONLY this file;
RVCConversion's contract and the rest of the pipeline stay unchanged.

Device: env JARVIS_RVC_DEVICE (default "mps"); PYTORCH_ENABLE_MPS_FALLBACK=1 is set so
any op MPS lacks falls back to CPU. rvc-python auto-detects an .index sitting next to
the .pth (JARVIS keeps both in voice_models/), so --index is informational here.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys


def _parse(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="rvc_infer_cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("convert")
    c.add_argument("in_wav")
    c.add_argument("out_wav")
    c.add_argument("--model", required=True)
    c.add_argument("--index", default=None)
    c.add_argument("--index-rate", dest="index_rate", default="0.75")
    c.add_argument("--f0-method", dest="f0_method", default="rmvpe")
    c.add_argument("--pitch", default="0")
    return ap.parse_args(argv)


def _build_rvc_python_cmd(a: argparse.Namespace, device: str) -> list[str]:
    cmd = [
        sys.executable, "-m", "rvc_python", "cli",
        "-i", a.in_wav, "-o", a.out_wav, "-mp", a.model,
        "-de", device, "-me", a.f0_method,
        "-pi", str(a.pitch), "-ir", str(a.index_rate),
    ]
    if a.index:                      # rvc-python's explicit index flag (-ip)
        cmd += ["-ip", a.index]
    # Similarity-tuning knobs, env-overridable without touching the convert contract:
    # protect (-pr) guards voiceless consonants (lower = stronger conversion),
    # rms_mix_rate (-rmr) mixes source/target loudness envelopes.
    protect = os.environ.get("JARVIS_RVC_PROTECT")
    if protect:
        cmd += ["-pr", protect]
    rms = os.environ.get("JARVIS_RVC_RMS")
    if rms:
        cmd += ["-rmr", rms]
    return cmd


def main(argv: list[str] | None = None) -> int:
    a = _parse(sys.argv[1:] if argv is None else argv)
    device = os.environ.get("JARVIS_RVC_DEVICE", "mps")
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
    return subprocess.run(_build_rvc_python_cmd(a, device)).returncode


if __name__ == "__main__":
    raise SystemExit(main())
