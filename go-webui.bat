@echo off
title RVC WebUI
setlocal
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
cd /d "%SCRIPT_DIR%"
set "PATH=%SCRIPT_DIR%\runtime;%PATH%"
set "GRADIO_ANALYTICS_ENABLED=False"
set "NO_PROXY=localhost,127.0.0.1,::1,%NO_PROXY%"
set "PYTHONUTF8=1"
echo ========================================
echo   RVC WebUI
echo ========================================
echo First launch may take about 20 seconds.
echo.
call "%SCRIPT_DIR%\tools\select-python.bat"
if errorlevel 1 goto :eof
"%RVC_PYTHON%" -I -X utf8 -m rvc_music.launcher --port 7897
if not errorlevel 1 exit /b 0
"%RVC_PYTHON%" -I webui.py --pycmd "%RVC_PYTHON%" --port 7897
if errorlevel 1 (
 echo.
 echo [ERROR] WebUI exited with code %errorlevel%.
) else (
 echo.
 echo [OK] WebUI closed.
)
echo.
pause
