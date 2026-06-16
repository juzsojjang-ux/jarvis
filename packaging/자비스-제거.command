#!/usr/bin/env bash
# 자비스(JARVIS) 완전 제거 — macOS
#
# 더블클릭하면 터미널에서 실행된다. 다음을 정리한다:
#   1) 실행 중인 자비스 종료
#   2) TCC 권한 항목 리셋(손쉬운 사용·입력 모니터링·화면 기록·마이크) — 재설치 시 섞임 방지
#   3) 사용자 데이터(~/.jarvis) 삭제  ← 장기 기억/로그/설정 포함
#   4) 앱 번들(JARVIS.app)·런처 삭제
#
# ⚠ 개발용 소스 repo(~/jarvis)는 건드리지 않는다. 배포 앱 흔적만 지운다.
set -u
BUNDLE_ID="com.jarvis.assistant"

echo "──────────────────────────────────────────"
echo "  자비스(JARVIS) 완전 제거"
echo "──────────────────────────────────────────"
printf "정말 제거할까요? 사용자 데이터(~/.jarvis: 장기기억·설정·로그)도 삭제됩니다. [y/N] "
read -r ans
case "$ans" in
  y|Y|yes|YES) ;;
  *) echo "취소했습니다."; exit 0;;
esac

echo "▸ 실행 중인 자비스 종료…"
pkill -f "JARVIS.app/Contents/MacOS/JARVIS" 2>/dev/null || true
pkill -f "jarvis_launch" 2>/dev/null || true
pkill -f "jarvis.hud" 2>/dev/null || true

echo "▸ 권한(TCC) 항목 리셋…"
for svc in Accessibility ListenEvent ScreenCapture Microphone; do
  tccutil reset "$svc" "$BUNDLE_ID" >/dev/null 2>&1 && echo "    - $svc 리셋" || true
done

echo "▸ 사용자 데이터 삭제(~/.jarvis)…"
rm -rf "$HOME/.jarvis"

echo "▸ 앱 번들 삭제…"
for app in "$HOME/Downloads/JARVIS.app" "$HOME/Desktop/JARVIS.app" \
           "/Applications/JARVIS.app" "$HOME/Applications/JARVIS.app"; do
  if [ -d "$app" ]; then rm -rf "$app" && echo "    - $app"; fi
done

echo "▸ 런처/바로가기 삭제…"
rm -f "$HOME/Desktop/자비스.command" "$HOME/Desktop/JARVIS.command" 2>/dev/null || true

echo ""
echo "✅ 제거 완료 — 자비스와 권한 흔적을 모두 지웠습니다."
echo "   (개발 소스 ~/jarvis 는 그대로 보존했습니다.)"
echo "   이 제거 스크립트 파일은 직접 삭제하셔도 됩니다."
echo ""
printf "엔터를 누르면 창이 닫힙니다… "
read -r _
