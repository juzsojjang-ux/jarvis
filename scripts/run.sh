#!/usr/bin/env bash
# Run JARVIS from the main venv. NO .app bundle — plain venv process.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
# Set HF_HUB_OFFLINE=1 once the whisper weights are cached locally.
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-0}"
exec python -m jarvis
