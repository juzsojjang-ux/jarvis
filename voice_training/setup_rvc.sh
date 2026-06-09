#!/usr/bin/env bash
# One-time bootstrap for the isolated RVC inference runtime (.venv-rvc).
#
# Mirrors the .venv-tts pattern: the RVC stack pins old numpy/numba/torch + fairseq,
# which cannot share the main venv. We build it in .venv-rvc and call it over a
# subprocess shim (jarvis/vc/rvc_infer_cli.py). Default runtime: rvc-python.
#
# Python 3.10 is REQUIRED here: the known-good RVC stack (numpy 1.23.5 / numba 0.56.4 /
# librosa 0.9.1) does not build on >=3.11 (numba 0.56 caps at <3.11). fairseq is the
# One-sixth fork (a clean-building 0.12.2). Idempotent: re-run to repair.
#
#   bash voice_training/setup_rvc.sh
#
# After this succeeds AND voice_models/jarvis.pth exists, JARVIS auto-speaks in the
# JARVIS timbre (vc_backend="auto"). Tune device with JARVIS_RVC_DEVICE (mps|cpu).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.venv-rvc"

# Resolve a Python 3.10 interpreter (install via brew if absent — bottled, fast).
PYV="${JARVIS_RVC_PYTHON:-}"
if [ -z "$PYV" ]; then
  if command -v python3.10 >/dev/null 2>&1; then PYV="python3.10"
  elif [ -x /opt/homebrew/opt/python@3.10/bin/python3.10 ]; then PYV="/opt/homebrew/opt/python@3.10/bin/python3.10"
  elif [ -x /usr/local/opt/python@3.10/bin/python3.10 ]; then PYV="/usr/local/opt/python@3.10/bin/python3.10"
  else
    echo "==> python3.10 not found; installing via brew (bottled)"
    brew install python@3.10
    PYV="$(brew --prefix)/opt/python@3.10/bin/python3.10"
  fi
fi
echo "==> RVC runtime bootstrap (.venv-rvc) using $PYV"
"$PYV" --version

# Recreate the venv if it isn't Python 3.10 (e.g. an earlier 3.11 attempt).
if [ -x "$VENV/bin/python" ] && ! "$VENV/bin/python" -c 'import sys; assert sys.version_info[:2]==(3,10)' 2>/dev/null; then
  echo "==> existing .venv-rvc is not 3.10; recreating"
  rm -rf "$VENV"
fi
[ -x "$VENV/bin/python" ] || "$PYV" -m venv "$VENV"

PIP="$VENV/bin/pip"
"$PIP" install -U pip wheel setuptools

echo "==> torch / torchaudio (Apple Silicon: default wheels carry MPS)"
"$PIP" install "torch>=2.1,<2.4" "torchaudio>=2.1,<2.4"

echo "==> fairseq (One-sixth fork — clean-building 0.12.2)"
"$PIP" install "git+https://github.com/One-sixth/fairseq.git"

echo "==> rvc-python (no deps) + RVC's known-good runtime stack (Python 3.10)"
"$PIP" install --no-deps rvc-python
"$PIP" install \
  "numpy==1.23.5" "scipy==1.10.1" "librosa==0.9.1" "numba==0.56.4" "llvmlite==0.39.1" \
  "soundfile>=0.12" "faiss-cpu==1.7.3" "torchcrepe>=0.0.20" "torchfcpe" \
  "praat-parselmouth>=0.4.3" "pyworld==0.3.2" "ffmpeg-python>=0.2.0" \
  "av" "loguru" "python-multipart" \
  "fastapi" "uvicorn" "requests" "tqdm" "audioread" "resampy"

echo "==> patching fairseq for torch>=2.6 (weights_only default change)"
"$VENV/bin/python" "$ROOT/voice_training/patch_fairseq.py"

echo "==> verifying rvc_python.infer actually imports (torch + fairseq + soundfile)"
"$VENV/bin/python" - <<'PY'
import rvc_python.infer  # noqa: F401  -- real import, not just find_spec
print("OK: rvc_python.infer imported")
PY

echo
echo "==> DONE. .venv-rvc (Python 3.10) ready."
echo "    Next: drop voice_models/jarvis.pth (+ optional added_*.index), then launch JARVIS."
echo "    Base models (hubert/rmvpe) auto-download on the first conversion."
