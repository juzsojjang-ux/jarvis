#!/usr/bin/env bash
# Synthesize a Korean sample through the FULL JARVIS chain:
#   MeloTTS-KR (.venv-tts) -> RVC timbre conversion (.venv-rvc, trained weight).
# Usage: bash voice_training/sample_rvc.sh <jarvis_weight.pth> [out.wav] ["문장"]
# Honors JARVIS_RVC_INDEX_PATH (optional), JARVIS_RVC_DEVICE, JARVIS_MELO_SPEED.
set -euo pipefail
JARVIS="$HOME/jarvis"
PTH="${1:?usage: sample_rvc.sh <weight.pth> [out.wav] [text]}"
OUT="${2:-$JARVIS/jarvis_rvc_sample.wav}"
TXT="${3:-안녕하세요 성재님, 저는 자비스입니다. 오늘도 무엇이든 말씀만 하십시오.}"
cd "$JARVIS"

echo "==> [1/2] MeloTTS-KR synth"
.venv/bin/python - "$TXT" <<'PY'
import asyncio, sys, wave, numpy as np
from jarvis.tts.melotts_kr import MeloTTSKR
t = MeloTTSKR(); t.warm()
pcm = asyncio.run(t.synth(sys.argv[1])); t.close()
x = np.clip(np.asarray(pcm, np.float32), -1, 1)
with wave.open("/tmp/melo_src.wav", "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(t.sample_rate)
    w.writeframes((x * 32767).astype("<i2").tobytes())
print("   melo src ok @", t.sample_rate)
PY

echo "==> [2/2] RVC convert (pitch -12, index_rate 0.9, similarity-first)"
# NOTE: macOS ships bash 3.2 — empty-array expansion under `set -u` is fatal there,
# so the optional index flag uses the ${arr[@]+...} guard.
IDX_ARGS=()
[ -n "${JARVIS_RVC_INDEX_PATH:-}" ] && IDX_ARGS=(--index "$JARVIS_RVC_INDEX_PATH")
.venv-rvc/bin/python jarvis/vc/rvc_infer_cli.py convert /tmp/melo_src.wav "$OUT" \
  --model "$PTH" ${IDX_ARGS[@]+"${IDX_ARGS[@]}"} \
  --index-rate 0.9 --f0-method rmvpe --pitch -12
echo "DONE -> $OUT"
ffprobe -v error -show_entries format=duration -of default=nk=1:nw=1 "$OUT" 2>/dev/null | xargs -I{} echo "duration {}s"
