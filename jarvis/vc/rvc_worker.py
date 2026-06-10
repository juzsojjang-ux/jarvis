#!/usr/bin/env python3
"""Persistent RVC worker. Runs INSIDE .venv-rvc ONLY, launched by
jarvis.vc.rvc_persistent.PersistentRVC. Loads hubert+rmvpe+jarvis.pth ONCE, then
converts per request — this removes the ~10s model-reload that made every spoken
sentence crawl when shelling out to `rvc_python cli` per call.

Line protocol on stdio (binary-safe via the same dup-stdout trick as tts_worker):
  worker -> "READY"                          after models load
  parent -> "CONVERT\t<in_wav>\t<out_wav>"   one request per line
  worker -> "OK" | "ERR <message>"

Config via env: JARVIS_RVC_MODEL (required), JARVIS_RVC_INDEX, JARVIS_RVC_DEVICE
(default mps), JARVIS_RVC_INDEX_RATE, JARVIS_RVC_F0_UP, JARVIS_RVC_PROTECT,
JARVIS_RVC_RMS, JARVIS_RVC_F0_METHOD.
"""
from __future__ import annotations

import os
import sys


def main() -> None:
    # Protect the line protocol from library prints: dup real stdout, point fd 1
    # at stderr (same trick as jarvis.tts.tts_worker).
    proto = os.fdopen(os.dup(sys.stdout.fileno()), "w", buffering=1)
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())

    # faiss search segfaults once torch's OMP runtime is up (macOS arm64) unless
    # faiss is single-threaded; MPS fallback keeps unsupported ops on CPU.
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

    from rvc_python.infer import RVCInference

    model = os.environ["JARVIS_RVC_MODEL"]
    index = os.environ.get("JARVIS_RVC_INDEX", "")
    device = os.environ.get("JARVIS_RVC_DEVICE", "mps")
    rvc = RVCInference(device=device)
    rvc.load_model(model, index_path=index)
    rvc.set_params(
        index_rate=float(os.environ.get("JARVIS_RVC_INDEX_RATE", "0.9")),
        f0up_key=int(os.environ.get("JARVIS_RVC_F0_UP", "-12")),
        f0method=os.environ.get("JARVIS_RVC_F0_METHOD", "rmvpe"),
        protect=float(os.environ.get("JARVIS_RVC_PROTECT", "0.33")),
        rms_mix_rate=float(os.environ.get("JARVIS_RVC_RMS", "0.25")),
    )
    proto.write("READY\n")

    for line in sys.stdin:
        parts = line.rstrip("\n").split("\t")
        if len(parts) != 3 or parts[0] != "CONVERT":
            proto.write("ERR bad request\n")
            continue
        _, in_wav, out_wav = parts
        try:
            rvc.infer_file(in_wav, out_wav)
            proto.write("OK\n")
        except Exception as exc:  # noqa: BLE001 - report, keep serving
            proto.write(f"ERR {exc!r}\n")


if __name__ == "__main__":
    main()
