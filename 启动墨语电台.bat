@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem ============================================================
rem  MoYu Radio launcher
rem  NOTE: this file MUST stay pure ASCII with CRLF line endings.
rem  cmd.exe reads .bat files as GBK, so any Chinese char breaks it.
rem ============================================================

set "LOG=%~dp0data\last-run.log"
set "RUNTIME=%~dp0runtime\python.exe"

rem ---- 1. Locate a usable Python interpreter --------------------------
rem  Priority:
rem    1. runtime\python.exe  - bundled with this app, always works
rem    2. a real installed Python (LocalAppData\Programs\Python\...)
rem    3. python on PATH, skipping the Microsoft Store stub
rem    4. WorkBuddy bundled interpreter
rem
rem  The WindowsApps\python.exe stub prints nothing and exits with 9009,
rem  so it MUST be excluded or the app silently fails to start.
set "PYEXE="

if exist "%RUNTIME%" set "PYEXE=%RUNTIME%"

if not defined PYEXE (
  for %%P in (
    "%LocalAppData%\Programs\Python\Python313\python.exe"
    "%LocalAppData%\Programs\Python\Python312\python.exe"
    "%LocalAppData%\Programs\Python\Python311\python.exe"
    "%LocalAppData%\Programs\Python\Python310\python.exe"
    "C:\Python313\python.exe"
    "C:\Python312\python.exe"
    "C:\Python311\python.exe"
  ) do (
    if exist %%P if not defined PYEXE set "PYEXE=%%~P"
  )
)

if not defined PYEXE (
  for /f "delims=" %%P in ('where python 2^>nul') do (
    if not defined PYEXE (
      echo %%P | find /i "WindowsApps" >nul || set "PYEXE=%%P"
    )
  )
)

if not defined PYEXE (
  for /d %%D in ("%USERPROFILE%\.workbuddy\binaries\python\versions\*") do (
    if not defined PYEXE if exist "%%D\python.exe" set "PYEXE=%%D\python.exe"
  )
)

if not defined PYEXE (
  echo.
  echo   [X] No usable Python found.
  echo.
  echo   The bundled runtime folder seems to be missing.
  echo   Re-download the whole moyu-radio folder, or install Python 3.10+
  echo   from https://www.python.org/downloads/ and tick "Add Python to PATH".
  echo.
  pause
  exit /b 1
)

rem ---- 2. Check dependencies, install if missing ----------------------
"%PYEXE%" -c "import PySide6, mutagen, requests, Crypto" >nul 2>&1
if errorlevel 1 (
  echo   Installing dependencies, please wait...
  "%PYEXE%" -m pip install --disable-pip-version-check -q -r requirements.txt
  if errorlevel 1 (
    echo.
    echo   [X] Failed to install dependencies.
    echo   Run this manually to see the error:
    echo     "%PYEXE%" -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
  )
)

rem ---- 3. Environment ------------------------------------------------
rem  Clear proxy vars: they break access to CN music platforms.
rem  Route app output to a log so the console stays readable.
set "http_proxy="
set "https_proxy="
set "HTTP_PROXY="
set "HTTPS_PROXY="
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "QT_ENABLE_HIGHDPI_SCALING=1"
rem  Silence the Qt ffmpeg backend's verbose probe output.
set "QT_LOGGING_RULES=qt.multimedia.ffmpeg=false;qt.multimedia=false;*.debug=false"

if not exist "%~dp0data" mkdir "%~dp0data"
if exist "%LOG%" del "%LOG%" >nul 2>&1

echo   Python : %PYEXE%
echo   Log    : %LOG%
echo   Starting MoYu Radio...
echo.

"%PYEXE%" app\main.py > "%LOG%" 2>&1
set "RC=%ERRORLEVEL%"

if "%RC%"=="0" goto :done

echo.
echo   [X] The app exited with code %RC%. Last lines of the log:
echo.
"%PYEXE%" -c "import sys;d=open(sys.argv[1],encoding='utf-8',errors='replace').read().splitlines();print('\n'.join(d[-25:]))" "%LOG%" 2>nul
echo.
pause
exit /b %RC%

:done
echo   App closed normally. Log kept at %LOG%
