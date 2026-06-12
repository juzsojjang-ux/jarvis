@echo off
setlocal
cd /d "%~dp0"

echo ==========================================
echo    JARVIS 디버그 실행 - 로그 수집
echo ==========================================
echo.

if exist "dist\JARVIS\JARVIS.exe" goto :run
echo [X] dist\JARVIS\JARVIS.exe 가 없습니다.
echo     BUILD_JARVIS.bat 을 먼저 실행해서 빌드하세요.
pause
exit /b 1

:run
echo  자비스를 실행하고 모든 출력을 jarvis_run.log 에 기록합니다.
echo  강제종료가 다시 나면 그냥 두세요. 끝나면 메모장이 자동으로 열립니다.
echo  메모장 내용을 복사해서 보내주시면 됩니다.
echo.

"dist\JARVIS\JARVIS.exe" > "jarvis_run.log" 2>&1
echo.
echo  종료 코드: %errorlevel%
echo  로그를 엽니다...
start "" notepad "jarvis_run.log"
pause
exit /b 0
