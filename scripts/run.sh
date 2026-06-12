#!/usr/bin/env bash
# Run JARVIS from the main venv. NO .app bundle — plain venv process.
#
# 크래시 자동 재기동(판매급 회복력): 비정상 종료(크래시)면 백오프 후 다시 띄운다.
# 정상 종료(exit 0)·Ctrl+C(130)·SIGTERM(143)은 재시작하지 않는다 — 사용자의 종료
# 의사를 존중한다. 연속 크래시 5회면 포기(크래시 루프 방지).
set -uo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
export PYTHONUNBUFFERED=1  # 로그 실시간(파이프 버퍼링 해제)
# Set HF_HUB_OFFLINE=1 once the whisper weights are cached locally.
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-0}"

MAX_CRASHES=5
crashes=0
while true; do
  python -m jarvis
  code=$?
  case "$code" in
    0|130|143) exit "$code" ;;  # 정상/Ctrl+C/SIGTERM — 의도된 종료
  esac
  crashes=$((crashes + 1))
  if [ "$crashes" -ge "$MAX_CRASHES" ]; then
    echo "[가드] 연속 크래시 ${crashes}회 — 재기동을 멈춥니다(로그를 확인하세요)." >&2
    exit "$code"
  fi
  delay=$((crashes * 3))
  echo "[가드] 자비스 비정상 종료(code=$code) — ${delay}초 후 자동 재기동(${crashes}/${MAX_CRASHES})." >&2
  sleep "$delay"
done
