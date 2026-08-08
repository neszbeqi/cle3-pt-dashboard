@echo off
title CLE3 PT Dashboard
cd /d "%~dp0"

REM Prefer local venv, fall back to the shared pt_env, then PATH
if exist "%~dp0venv\Scripts\python.exe" (
    set PYTHON=%~dp0venv\Scripts\python.exe
) else if exist "C:\Users\neszbeqi\Downloads\pt_env\Scripts\python.exe" (
    set PYTHON=C:\Users\neszbeqi\Downloads\pt_env\Scripts\python.exe
) else (
    set PYTHON=python
)

echo.
echo  CLE3 PT Dashboard
echo  Checking for updates...
REM "%PYTHON%" updater.py  (disabled - code managed manually)
echo.
echo  Starting server...
start "" "firefox.exe" "http://localhost:5050"
"%PYTHON%" server.py
pause

