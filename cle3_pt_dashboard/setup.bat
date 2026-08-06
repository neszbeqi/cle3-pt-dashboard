@echo off
title CLE3 PT Dashboard - Setup
cd /d "%~dp0"
echo.
echo  CLE3 PT Dashboard - First-Time Setup
echo  ======================================
echo.

REM Check for Python
python --version >nul 2>&1
if errorlevel 1 (
    echo Python not found. Installing via winget...
    winget install Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
    if errorlevel 1 (
        echo.
        echo  ERROR: Could not install Python automatically.
        echo  Please install Python from https://python.org then run setup again.
        pause
        exit /b 1
    )
    echo Python installed successfully.
    echo.
    echo  Please close this window and run setup.bat again to continue.
    pause
    exit /b 0
)

echo Python found.
echo.

REM Create local venv if not already present
if not exist "%~dp0venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv "%~dp0venv"
    if errorlevel 1 (
        echo ERROR: Could not create virtual environment.
        pause
        exit /b 1
    )
    echo Virtual environment created.
) else (
    echo Virtual environment already exists.
)

echo.
echo Installing Python packages...
"%~dp0venv\Scripts\pip.exe" install --quiet --upgrade pip
"%~dp0venv\Scripts\pip.exe" install --quiet flask playwright
if errorlevel 1 (
    echo ERROR: Package install failed. Check your internet connection.
    pause
    exit /b 1
)

echo.
echo Installing browser for FCLM login (one-time, may take 1-2 minutes)...
"%~dp0venv\Scripts\playwright.exe" install chromium
if errorlevel 1 (
    echo WARNING: Browser install may have failed. You can try running this again.
)

echo.
echo  ======================================
echo  Setup complete!
echo  Double-click run.bat to start the dashboard.
echo  ======================================
echo.
pause
