#!/usr/bin/env bash
# One-time bootstrap for the JARVIS voice via Kyutai Pocket TTS (.venv-pocket).
# This is the engine from the NetHyTech "real JARVIS voice" video: 100M CPU model,
# real-time, instant voice cloning from a ~20s reference. ENGLISH-only.
#
#   bash voice_training/setup_pocket.sh
#
# Voice cloning weights are GATED on Hugging Face, so two one-time manual steps:
#   1) Visit https://huggingface.co/kyutai/pocket-tts and click "Agree and access".
#   2) Create a Hugging Face token of type "Read" (NOT fine-grained — it lacks gated
#      access) at https://huggingface.co/settings/tokens, then:
#        ~/jarvis/.venv-pocket/bin/hf auth login --token hf_xxx
#
# After that, tts_backend="pocket" speaks Korean prompts back in the JARVIS English voice.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.venv-pocket"
PYV="${JARVIS_POCKET_PYTHON:-python3.11}"

command -v "$PYV" >/dev/null 2>&1 || { echo "ERROR: $PYV not found. brew install python@3.11"; exit 1; }
echo "==> Pocket TTS runtime bootstrap (.venv-pocket) using $PYV"
[ -x "$VENV/bin/python" ] || "$PYV" -m venv "$VENV"
"$VENV/bin/pip" install -U pip wheel >/dev/null
echo "==> installing pocket-tts"
"$VENV/bin/pip" install pocket-tts

echo "==> verify"
"$VENV/bin/python" -c "import pocket_tts; print('pocket-tts OK')"
echo
echo "==> DONE. Next: accept the HF license + 'hf auth login --token' (see header),"
echo "    then the JARVIS English voice auto-activates (tts_backend=pocket)."
