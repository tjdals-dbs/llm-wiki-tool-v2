@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python is not available. Install Python 3.11 or newer, then run setup.bat again.
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment in .venv...
    python -m venv .venv
    if errorlevel 1 (
        echo Failed to create the Python virtual environment.
        exit /b 1
    )
)

echo Upgrading pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 (
    echo Failed to upgrade pip.
    exit /b 1
)

echo Installing project dependencies...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Failed to install dependencies from requirements.txt.
    exit /b 1
)

echo Setup complete. Run run_app.bat to start the desktop app.
exit /b 0
