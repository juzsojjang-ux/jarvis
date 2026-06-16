@echo off
chcp 65001 >nul
setlocal
rem 자비스(JARVIS) 완전 제거 — Windows
rem 더블클릭하면 실행된다. 윈도우는 macOS 같은 권한(TCC) DB가 없어, 권한 리셋은 불필요.
rem   1) 실행 중인 자비스 종료
rem   2) 사용자 데이터(%USERPROFILE%\.jarvis) 삭제  ← 장기 기억/로그/설정 포함
rem   3) 바로가기 삭제
rem ※ 앱 폴더(JARVIS) 자체는 이 스크립트가 그 안에 있을 수 있어 직접 못 지움 — 끝나면 폴더를 통째로 삭제하세요.

echo ──────────────────────────────────────────
echo   자비스(JARVIS) 완전 제거
echo ──────────────────────────────────────────
set /p ans="정말 제거할까요? 사용자 데이터(.jarvis: 장기기억·설정·로그)도 삭제됩니다. [y/N] "
if /i not "%ans%"=="y" (
  echo 취소했습니다.
  pause
  exit /b 0
)

echo ▸ 실행 중인 자비스 종료…
taskkill /F /IM JARVIS.exe >nul 2>&1

echo ▸ 사용자 데이터 삭제(%USERPROFILE%\.jarvis)…
rmdir /s /q "%USERPROFILE%\.jarvis" >nul 2>&1

echo ▸ 바로가기 삭제…
del /f /q "%USERPROFILE%\Desktop\자비스.lnk" >nul 2>&1
del /f /q "%USERPROFILE%\Desktop\JARVIS.lnk" >nul 2>&1

echo.
echo ✅ 제거 완료 — 자비스 사용자 데이터를 지웠습니다.
echo    이제 압축을 풀었던 JARVIS 폴더(이 파일이 든 폴더)를 통째로 삭제하시면 끝납니다.
echo.
pause
