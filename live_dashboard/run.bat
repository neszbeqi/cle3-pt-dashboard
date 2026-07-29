@echo off
title CLE3 Live Dashboard
cd /d "%~dp0"
set VENV=C:\Users\neszbeqi\Downloads\pt_env\Scripts\python.exe
if not exist "%VENV%" (
    echo Python venv not found at %VENV%
    echo Please run setup.bat from PT_Dashboard first.
    pause
    exit /b 1
)
echo Starting CLE3 Live Dashboard...
echo Open http://localhost:5000 in your browser
echo.
"%VENV%" server.py
pause
