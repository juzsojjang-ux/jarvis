#!/usr/bin/env bash
# Local RVC training on Apple Silicon via Applio (headless CLI). Produces the
# trained JARVIS timbre model and drops it into voice_models/ so vc_backend="auto"
# picks it up on the next launch.
#
# Pipeline: prerequisites(pretrained base) -> preprocess(slice/40k) -> extract
# (rmvpe f0 + contentvec) -> train (MPS, overtraining detector, periodic weights)
# -> index -> copy best weight + index to ~/jarvis/voice_models/.
#
#   bash voice_training/train_applio_local.sh [DATASET_DIR] [EPOCHS]
#
# Defaults: DATASET=~/jarvis/voice_data/jarvis_train, EPOCHS=300. Training on an
# M4 Pro runs on MPS (Applio rvc/train/train.py auto-selects mps) — expect HOURS.
# Weights are saved every 25 epochs, so partial results are usable early:
# re-run the COPY step manually anytime (see bottom).
set -euo pipefail

APPLIO="${APPLIO_DIR:-$HOME/Applio}"
JARVIS="$HOME/jarvis"
DATASET="${1:-$JARVIS/voice_data/jarvis_train}"
EPOCHS="${2:-300}"
MODEL="jarvis"
SR=40000
PY="$APPLIO/.venv/bin/python"
CORES="$(sysctl -n hw.perflevel0.logicalcpu 2>/dev/null || echo 8)"

[ -x "$PY" ] || { echo "ERROR: $PY missing — install Applio venv first"; exit 1; }
[ -d "$DATASET" ] || { echo "ERROR: dataset $DATASET missing"; exit 1; }
cd "$APPLIO"
export PYTORCH_ENABLE_MPS_FALLBACK=1   # any op MPS lacks falls back to CPU

echo "==> [1/5] prerequisites (pretrained HiFi-GAN base + models)"
"$PY" core.py prerequisites --pretraineds_hifigan True --models True --exe False

echo "==> [2/5] preprocess  (dataset=$DATASET, sr=$SR, cores=$CORES)"
"$PY" core.py preprocess --model_name "$MODEL" --dataset_path "$DATASET" \
  --sample_rate $SR --cpu_cores "$CORES" --cut_preprocess Automatic \
  --process_effects False --noise_reduction False --normalization_mode none

echo "==> [3/5] extract  (f0=rmvpe, embedder=contentvec)"
# NOTE: --include_mutes is REQUIRED by core.py (despite the default in help).
# embedder stays contentvec: the rvc-python inference runtime is contentvec-based,
# so training with korean-hubert-base would break inference compatibility.
"$PY" core.py extract --model_name "$MODEL" --sample_rate $SR \
  --cpu_cores "$CORES" --f0_method rmvpe --embedder_model contentvec --include_mutes 2

echo "==> [4/5] train  (epochs=$EPOCHS, batch=8, MPS, overtraining detector on)"
"$PY" core.py train --model_name "$MODEL" --vocoder HiFi-GAN --sample_rate $SR \
  --total_epoch "$EPOCHS" --batch_size 8 --save_every_epoch 25 \
  --save_only_latest False --save_every_weights True --pretrained True \
  --overtraining_detector True --overtraining_threshold 50 \
  --cache_data_in_gpu False --gpu 0

echo "==> [5/5] index"
"$PY" core.py index --model_name "$MODEL" --index_algorithm Auto

echo "==> copying newest weight + index to $JARVIS/voice_models/"
LOGDIR="$APPLIO/logs/$MODEL"
BEST_PTH="$(ls -t "$LOGDIR"/*.pth 2>/dev/null | grep -v 'D_\|G_' | head -1 || true)"
BEST_IDX="$(ls -t "$LOGDIR"/added_*.index 2>/dev/null | head -1 || true)"
[ -n "$BEST_PTH" ] && cp "$BEST_PTH" "$JARVIS/voice_models/jarvis.pth" && echo "  -> jarvis.pth  ($(basename "$BEST_PTH"))"
[ -n "$BEST_IDX" ] && cp "$BEST_IDX" "$JARVIS/voice_models/" && echo "  -> $(basename "$BEST_IDX")"
echo "DONE. Next launch: vc_backend=auto detects voice_models/jarvis.pth automatically."
