@echo off
set "RVC_PYTHON="
if exist "%SCRIPT_DIR%\runtime\python.exe" set "RVC_PYTHON=%SCRIPT_DIR%\runtime\python.exe"
if not defined RVC_PYTHON if exist "%SCRIPT_DIR%\.venv\Scripts\python.exe" set "RVC_PYTHON=%SCRIPT_DIR%\.venv\Scripts\python.exe"
if defined RVC_PYTHON exit /b 0
echo [ERROR] Python environment not found. See docs\INSTALLATION.md.
pause
exit /b 1
