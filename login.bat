@echo off
title CLE3 PT - Login Helper
cd /d "%~dp0"
echo.
echo  CLE3 PT Dashboard - Login Helper
echo  ----------------------------------
echo  This will open a browser window.
echo  Log in to FCLM and SCC when prompted.
echo  Session is saved for the shift.
echo.

set PYTHON=
for %%p in (
  "%~dp0..\pt_env\Scripts\python.exe"
  "C:\Users\neszbeqi\Downloads\pt_env\Scripts\python.exe"
  "%USERPROFILE%\pt_env\Scripts\python.exe"
  "python"
) do (
  if exist "%%~p" (
    set PYTHON=%%~p
    goto :found
  )
)
where python >nul 2>&1 && set PYTHON=python
:found

if "%PYTHON%"=="" (
  echo ERROR: Python not found. Run setup.bat first.
  pause
  exit /b 1
)

%PYTHON% login_helper.py
