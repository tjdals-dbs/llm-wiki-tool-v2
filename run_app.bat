@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Python environment is not ready. Run setup.bat first.
    exit /b 1
)
".venv\Scripts\python.exe" scripts\run_app.py %*
