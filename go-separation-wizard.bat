@echo off
title RVC Separation Wizard
setlocal
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
cd /d "%SCRIPT_DIR%"
set "PATH=%SCRIPT_DIR%\runtime;%PATH%"
set "GRADIO_ANALYTICS_ENABLED=False"
set "NO_PROXY=localhost,127.0.0.1,::1"
set "PYTHONUTF8=1"
echo ========================================
echo   RVC Separation Wizard
echo ========================================
echo.
call "%SCRIPT_DIR%\tools\select-python.bat"
if errorlevel 1 goto :eof
"%RVC_PYTHON%" -I -X utf8 separation_wizard.py
if errorlevel 1 (
 echo.
 echo [ERROR] Separation wizard exited with code %errorlevel%.
) else (
 echo.
 echo [OK] Wizard closed.
)
echo.
pause
