#!/usr/bin/env bash
# upgrade_full_voice.sh — 배포 번들을 '개인용 풀음성'으로 업그레이드(macOS).
#
# 배포 JARVIS는 기본 torch-free(edge-tts → ONNX RVC)다. 이 스크립트는 개인용과
# *동일한* 음성 체인을 사용자 컴퓨터에 설치한다:
#   • pocket (기본) : Kyutai Pocket TTS = 개인용 기본 음성(영어 자비스, 그대로).
#   • rvc          : MeloTTS-KR → torch-RVC = 개인용 한국어 음색 옵션(무거움).
#
# 설치 후 ~/.jarvis/voice_full.json 마커를 남기면, 다음 실행부터 launcher가
# edge/onnx 대신 이 체인을 켠다(jarvis/core/voice_full.py). torch 설치는 전적으로
# 이 컴퓨터에서, 사용자가 이걸 실행할 때만 일어난다(배포물 자체는 가볍게 유지).
#
#   bash upgrade_full_voice.sh [--mode pocket|rvc] [--bundle <dir>]
#
# 멱등: 재실행하면 venv를 고치고 마커를 다시 쓴다. --bundle 미지정 시
# JARVIS_BUNDLE_ROOT(번들 런처가 export) → 스크립트 디렉토리 순으로 자산을 찾는다.
set -euo pipefail

MODE="pocket"
BUNDLE="${JARVIS_BUNDLE_ROOT:-}"
while [ $# -gt 0 ]; do
  case "$1" in
    --mode) MODE="$2"; shift 2;;
    --bundle) BUNDLE="$2"; shift 2;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -n "$BUNDLE" ] || BUNDLE="$SELF_DIR"

# --- 번들 자산 위치 해석(프로즌 레이아웃 우선, repo 폴백) ----------------------
find_src() {
  for c in "$BUNDLE/voice_full_src" "$BUNDLE/../Resources/voice_full_src" \
           "$BUNDLE" "$SELF_DIR/.."; do
    [ -d "$c/jarvis" ] && { echo "$c"; return 0; }
  done
  echo ""; return 1
}
find_assets() {
  for c in "$BUNDLE/voice_full_assets" "$BUNDLE/../Resources/voice_full_assets" \
           "$SELF_DIR/../voice_models"; do
    [ -d "$c" ] && { echo "$c"; return 0; }
  done
  echo ""; return 1
}

SRC_BUNDLE="$(find_src)"
ASSETS="$(find_assets)"
[ -n "$SRC_BUNDLE" ] || { echo "ERROR: jarvis 소스 트리를 못 찾음(번들 손상?)" >&2; exit 1; }
[ -n "$ASSETS" ]     || { echo "ERROR: 음성 모델 자산 디렉토리를 못 찾음" >&2; exit 1; }

BASE="$HOME/.jarvis/voice-full"
SRC="$BASE/src"
MODELS="$BASE/models"
MARKER="$HOME/.jarvis/voice_full.json"
mkdir -p "$SRC" "$MODELS"

echo "==> 풀음성 업그레이드 (mode=$MODE)"
echo "    bundle=$BUNDLE"
echo "    base=$BASE"

# --- 워커가 import할 jarvis 소스 배치 -----------------------------------------
echo "==> jarvis 소스 복사 → $SRC"
rm -rf "$SRC/jarvis"
cp -R "$SRC_BUNDLE/jarvis" "$SRC/jarvis"

# venv의 site-packages에 .pth 한 줄을 박아 jarvis를 import 가능하게(워커는 별도 venv).
inject_pth() {
  local venv="$1"
  local sp
  sp="$("$venv/bin/python" -c 'import site; print(site.getsitepackages()[0])')"
  printf '%s\n' "$SRC" > "$sp/_jarvis_src.pth"
  echo "    .pth → $sp/_jarvis_src.pth"
}

# --- JSON 마커 작성(파이썬 stdlib로 안전하게) ---------------------------------
# 사용법: write_marker <pybin> <mode> KEY=VAL KEY=VAL ...
write_marker() {
  local pybin="$1"; local mode="$2"; shift 2
  "$pybin" -c '
import json, sys
mode, marker = sys.argv[1], sys.argv[2]
env = dict(p.split("=", 1) for p in sys.argv[3:])
verify = [v for k, v in env.items() if k.endswith("_PYTHON") or k.endswith("_MODEL_PATH")]
json.dump({"version": 1, "mode": mode, "env": env, "verify_paths": verify},
          open(marker, "w"), ensure_ascii=False, indent=2)
print("==> 마커 작성:", marker)
' "$mode" "$MARKER" "$@"
}

if [ "$MODE" = "pocket" ]; then
  VENV="$BASE/venv-pocket"
  HFCACHE="$BASE/hf-cache"
  PYV="${JARVIS_POCKET_PYTHON_BIN:-python3.11}"
  command -v "$PYV" >/dev/null 2>&1 || { echo "ERROR: $PYV 없음. brew install python@3.11" >&2; exit 1; }
  echo "==> Pocket venv 생성 → $VENV ($PYV)"
  [ -x "$VENV/bin/python" ] || "$PYV" -m venv "$VENV"
  "$VENV/bin/pip" install -U pip wheel >/dev/null
  echo "==> pocket-tts + 런타임 의존성 설치(torch 포함 — 수백 MB)"
  "$VENV/bin/pip" install pocket-tts numpy soundfile

  # --- 음색 가중치(209MB, CC-BY-4.0): 토큰 없이 우리 릴리스에서 받아 HF 캐시에 배치 ---
  # Kyutai pocket-tts 가중치는 HF에서 게이트(수동 동의)되지만 라이선스가 CC-BY-4.0이라
  # 재배포가 허용된다(© Kyutai, CC-BY-4.0). 받아서 오프라인으로 쓰므로 수신자는 HF
  # 계정·토큰·동의가 전혀 필요 없다. 오프라인 플래그는 Pocket 워커에만 스코프된다
  # (JARVIS_POCKET_HF_HOME) — 전역 HF_HUB_OFFLINE은 Whisper STT 첫 다운로드를 막는다.
  WEIGHTS_URL="${JARVIS_POCKET_WEIGHTS_URL:-https://github.com/juzsojjang-ux/jarvis/releases/download/voice-weights/pocket-voice-weights.tar.gz}"
  if [ ! -d "$HFCACHE/hub/models--kyutai--pocket-tts" ]; then
    echo "==> 음색 가중치 내려받기(≈167MB) → $HFCACHE"
    mkdir -p "$HFCACHE"
    TARB="$BASE/pocket-weights.tar.gz"
    if command -v curl >/dev/null 2>&1; then
      curl -fL --retry 3 -o "$TARB" "$WEIGHTS_URL"
    else
      wget -O "$TARB" "$WEIGHTS_URL"
    fi
    tar -xzf "$TARB" -C "$HFCACHE"
    rm -f "$TARB"
  else
    echo "==> 음색 가중치 이미 있음 — 건너뜀"
  fi

  cp -f "$ASSETS/jarvis_en_ref.wav" "$MODELS/jarvis_en_ref.wav"
  inject_pth "$VENV"
  write_marker "$VENV/bin/python" pocket \
    "JARVIS_TTS_BACKEND=pocket" \
    "JARVIS_VC_BACKEND=null" \
    "JARVIS_REPLY_LANGUAGE=en" \
    "JARVIS_POCKET_PYTHON=$VENV/bin/python" \
    "JARVIS_POCKET_REF_PATH=$MODELS/jarvis_en_ref.wav" \
    "JARVIS_POCKET_HF_HOME=$HFCACHE"
  echo
  echo "==> Pocket 음성 설치 완료 — HF 토큰 불필요. JARVIS를 재시작하세요."
  echo "    음색 모델: Kyutai pocket-tts (CC-BY-4.0)"

elif [ "$MODE" = "rvc" ]; then
  # 개인용 한국어 음색: MeloTTS-KR → torch-RVC. torch/fairseq 빌드라 무겁다.
  RVC="$BASE/venv-rvc"
  PYV="${JARVIS_RVC_PYTHON_BIN:-python3.10}"
  command -v "$PYV" >/dev/null 2>&1 || { echo "ERROR: $PYV 없음. brew install python@3.10" >&2; exit 1; }
  echo "==> RVC venv 생성 → $RVC ($PYV) — torch/fairseq, 수 분 소요"
  [ -x "$RVC/bin/python" ] || "$PYV" -m venv "$RVC"
  "$RVC/bin/pip" install -U pip wheel setuptools >/dev/null
  "$RVC/bin/pip" install "torch>=2.1,<2.4" "torchaudio>=2.1,<2.4"
  "$RVC/bin/pip" install "git+https://github.com/One-sixth/fairseq.git"
  "$RVC/bin/pip" install --no-deps rvc-python
  "$RVC/bin/pip" install \
    "numpy==1.23.5" "scipy==1.10.1" "librosa==0.9.1" "numba==0.56.4" "llvmlite==0.39.1" \
    "soundfile>=0.12" "faiss-cpu==1.7.3" "torchcrepe>=0.0.20" "torchfcpe" \
    "praat-parselmouth>=0.4.3" "pyworld==0.3.2" "ffmpeg-python>=0.2.0" \
    "av" "loguru" "tqdm" "audioread" "resampy"
  cp -f "$ASSETS/jarvis.pth"   "$MODELS/jarvis.pth"
  [ -f "$ASSETS/jarvis.index" ] && cp -f "$ASSETS/jarvis.index" "$MODELS/jarvis.index"
  inject_pth "$RVC"
  # NOTE: MeloTTS 베이스(.venv-tts)는 별도 무거운 설치 — 여기선 RVC 음색만 켜고
  # 베이스 TTS는 edge로 두는 절충(edge → torch-RVC). 순수 개인용 MeloTTS 베이스가
  # 필요하면 docs/PACKAGING.md의 MeloTTS 설치를 따른다.
  write_marker "$RVC/bin/python" rvc \
    "JARVIS_TTS_BACKEND=edge" \
    "JARVIS_VC_BACKEND=rvc" \
    "JARVIS_RVC_PYTHON=$RVC/bin/python" \
    "JARVIS_RVC_MODEL_PATH=$MODELS/jarvis.pth" \
    "JARVIS_RVC_INDEX_PATH=$MODELS/jarvis.index" \
    "JARVIS_RVC_F0_UP=0"
  echo "==> RVC 음색 설치 완료(edge 베이스 → 자비스 음색)."
else
  echo "ERROR: --mode 는 pocket | rvc" >&2; exit 2
fi

echo "==> 완료. JARVIS를 재시작하세요."
