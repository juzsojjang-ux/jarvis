@echo off
setlocal
cd /d "%~dp0"

echo ==========================================
echo    JARVIS - Windows EXE 자동 빌드
echo ==========================================
echo.
echo  자비스는 Python 3.11 전용입니다.
echo  3.11 을 찾고, 없으면 자동 설치를 시도합니다.
echo.

set "PYEXE="
set "RETRIED="
set "TRIED_LOCAL="

:findpy
rem --- 1. py 런처에서 3.11 찾기 -----------------------------------
py -3.11 -c "import sys" >nul 2>nul
if errorlevel 1 goto :try_python
for /f "delims=" %%p in ('py -3.11 -c "import sys;print(sys.executable)"') do set "PYEXE=%%p"
goto :found

:try_python
rem --- 2. python 명령이 3.11 인지 확인 ----------------------------
python -c "import sys; sys.exit(0 if sys.version_info[:2]==(3,11) else 1)" >nul 2>nul
if errorlevel 1 goto :try_paths
for /f "delims=" %%p in ('python -c "import sys;print(sys.executable)"') do set "PYEXE=%%p"
goto :found

:try_paths
rem --- 3. 흔한 설치 경로 직접 확인 --------------------------------
if exist "%LocalAppData%\Programs\Python\Python311\python.exe" set "PYEXE=%LocalAppData%\Programs\Python\Python311\python.exe"
if defined PYEXE goto :found
if exist "C:\Program Files\Python311\python.exe" set "PYEXE=C:\Program Files\Python311\python.exe"
if defined PYEXE goto :found

rem --- 4. 없으면 동봉된 설치 파일로 자동 설치 ----------------------
if defined TRIED_LOCAL goto :try_winget
if not exist "python-3.11.9-amd64.exe" goto :try_winget
echo [!] Python 3.11 이 없습니다. 다른 버전 Python 으로는 빌드가 안 됩니다.
echo     동봉된 Python 3.11 설치 파일로 자동 설치합니다... 1~2분 기다리세요.
echo.
set "TRIED_LOCAL=1"
start /wait "" "%CD%\python-3.11.9-amd64.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_test=0
goto :findpy

:try_winget
rem --- 5. 그래도 없으면 winget 자동 설치 ---------------------------
if defined RETRIED goto :manual
winget --version >nul 2>nul
if errorlevel 1 goto :manual
echo     winget 으로 Python 3.11 자동 설치를 시도합니다... 1~2분 기다리세요.
echo.
winget install -e --id Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
set "RETRIED=1"
goto :findpy

:manual
echo.
echo [X] 자동 설치가 안 됐습니다. 직접 설치해주세요:
echo     1. 지금 열리는 페이지 아래쪽 Files 에서
echo        "Windows installer 64-bit" 를 받아 설치하세요.
echo     2. 설치 첫 화면 맨 아래 "Add python.exe to PATH" 를 꼭 체크하세요.
echo     3. 설치가 끝나면 이 BUILD_JARVIS.bat 을 다시 더블클릭하세요.
echo.
start "" "https://www.python.org/downloads/release/python-3119/"
pause
exit /b 1

:found
echo [OK] Python 3.11 확인:
"%PYEXE%" --version
echo      위치: %PYEXE%
echo.

rem --- 가상환경: 없거나 3.11 이 아니면 새로 만든다 -----------------
if not exist ".venv\Scripts\python.exe" goto :mkvenv
".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info[:2]==(3,11) else 1)" >nul 2>nul
if not errorlevel 1 goto :havevenv
echo [!] 기존 가상환경이 다른 Python 버전으로 만들어져 있어 지우고 다시 만듭니다...
rmdir /s /q .venv

:mkvenv
echo [1/4] 가상환경 만드는 중...
"%PYEXE%" -m venv .venv
if errorlevel 1 goto :fail

:havevenv
echo [2/4] 필요한 패키지 설치 중... 인터넷 속도에 따라 몇 분 걸립니다.
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul 2>nul
".venv\Scripts\pip.exe" install -e ".[dev,winhud]"
if errorlevel 1 goto :fail
echo.

echo [3/4] JARVIS.exe 빌드 중... 시간이 걸립니다. 창을 닫지 마세요.
".venv\Scripts\pip.exe" install --upgrade "pyinstaller>=6.0"
if errorlevel 1 goto :fail
".venv\Scripts\pyinstaller.exe" packaging\jarvis.spec --noconfirm
if errorlevel 1 goto :fail
echo.

echo [4/4] 완료!
echo.
if not exist "dist\JARVIS\JARVIS.exe" goto :noexe

echo   ====================================================
echo    실행파일이 만들어졌습니다:
echo      %CD%\dist\JARVIS\JARVIS.exe
echo.
echo    이 JARVIS.exe 를 더블클릭하면 자비스가 켜집니다.
echo.
echo    처음 실행 때 "알 수 없는 앱" 경고가 뜨면
echo    "추가 정보" 누른 뒤 "실행" 을 누르세요. 정상입니다.
echo   ====================================================
echo.
echo    실행파일 폴더를 엽니다...
explorer "dist\JARVIS"
pause
exit /b 0

:noexe
echo  [!] 빌드는 끝났지만 JARVIS.exe 를 찾지 못했습니다.
echo      위 로그의 에러 메시지를 확인하세요.
pause
exit /b 1

:fail
echo.
echo [X] 실패했습니다. 위 메시지를 확인한 뒤 다시 시도하세요.
pause
exit /b 1
