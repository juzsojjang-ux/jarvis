#!/usr/bin/env bash
# One-time bootstrap for the JARVIS voice via XTTS-v2 zero-shot cloning (.venv-xtts).
#
# This is the NO-TRAINING path: it clones the JARVIS timbre directly from a short
# reference wav (voice_models/jarvis_ref.wav) built from your own JARVIS voice clips —
# no Colab, no GPU, no RVC .pth. Isolated venv (coqui-tts pins torch/transformers).
#
#   bash voice_training/setup_xtts.sh                  # install the runtime
#   bash voice_training/setup_xtts.sh /path/to/clips   # also (re)build the reference wav
#
# After this, tts_backend="auto" auto-selects the JARVIS voice. Device: JARVIS_XTTS_DEVICE
# (cpu default; mps faster but occasionally flaky). Tune JARVIS_XTTS_TEMP / JARVIS_XTTS_REP.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.venv-xtts"
PYV="${JARVIS_XTTS_PYTHON:-python3.11}"   # coqui-tts supports 3.10–3.11

command -v "$PYV" >/dev/null 2>&1 || { echo "ERROR: $PYV not found. brew install python@3.11"; exit 1; }
echo "==> XTTS runtime bootstrap (.venv-xtts) using $PYV"
[ -x "$VENV/bin/python" ] || "$PYV" -m venv "$VENV"
PIP="$VENV/bin/pip"
"$PIP" install -U pip wheel setuptools

echo "==> coqui-tts (maintained XTTS fork) + torch + codec; transformers pinned <5"
"$PIP" install "coqui-tts[codec]" torch torchaudio torchcodec "transformers>=4.40,<5"

echo "==> verify TTS + XTTS import"
COQUI_TOS_AGREED=1 "$VENV/bin/python" -c "from TTS.api import TTS; print('coqui-tts OK')"

# Optional: (re)build the reference wav from a folder of JARVIS voice clips (mp3/wav).
CLIPS="${1:-}"
if [ -n "$CLIPS" ] && [ -d "$CLIPS" ]; then
  echo "==> building voice_models/jarvis_ref.wav from the 8 longest clips in $CLIPS"
  mkdir -p "$ROOT/voice_models"
  list="$(mktemp)"
  for f in "$CLIPS"/*.mp3 "$CLIPS"/*.wav; do
    [ -f "$f" ] || continue
    d="$(ffprobe -v error -show_entries format=duration -of default=nk=1:nw=1 "$f" 2>/dev/null || echo 0)"
    printf "%s %s\n" "$d" "$f"
  done | sort -rn | head -8 | awk '{ $1=""; sub(/^ /,""); printf "file '\''%s'\''\n", $0 }' > "$list"
  ffmpeg -y -f concat -safe 0 -i "$list" -ac 1 -ar 22050 "$ROOT/voice_models/jarvis_ref.wav"
  echo "    reference: $ROOT/voice_models/jarvis_ref.wav"
fi

echo
echo "==> DONE. The JARVIS voice (XTTS) auto-activates when .venv-xtts + voice_models/jarvis_ref.wav exist."
