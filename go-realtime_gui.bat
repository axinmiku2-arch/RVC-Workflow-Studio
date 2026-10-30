@echo off
title RVC Realtime GUI
setlocal
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
cd /d "%SCRIPT_DIR%"
set "PATH=%SCRIPT_DIR%\runtime;%PATH%"
set "PYTHONUTF8=1"
echo ========================================
echo   RVC Realtime GUI
echo ========================================
echo First launch may take about 20 seconds.
echo.
call "%SCRIPT_DIR%\tools\select-python.bat"
if errorlevel 1 goto :eof
"%RVC_PYTHON%" -I realtime_gui.py
if errorlevel 1 (
 echo.
 echo [ERROR] Realtime GUI exited with code %errorlevel%.
) else (
 echo.
 echo [OK] Realtime GUI closed.
)
echo.
pause
