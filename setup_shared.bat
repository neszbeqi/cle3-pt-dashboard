@echo off
setlocal
title CLE3 PT Dashboard - Shared Setup

echo.
echo  ================================================
echo   CLE3 PT Dashboard - Shared Setup
echo  ================================================
echo.
echo  This installs the dashboard on YOUR machine.
echo  Once installed, YOU become a backup server.
echo  Any AM with this installed keeps data flowing
echo  even when other AMs are offline.
echo.
echo  You need a GitHub Personal Access Token.
echo  Instructions:
echo    1. Go to github.com -^> Settings -^> Developer settings
echo    2. Personal access tokens -^> Fine-grained tokens -^> Generate new token
echo    3. Repository: neszbeqi/cle3-pt-dashboard
echo    4. Permissions: Contents = Read and Write
echo    5. Copy the token and paste it below
echo.

set /p GITHUB_TOKEN="Paste your GitHub token here: "

if "%GITHUB_TOKEN%"=="" (
    echo ERROR: No token entered. Exiting.
    pause
    exit /b 1
)

REM Write agent_config.json
echo {"github_token": "%GITHUB_TOKEN%", "github_repo": "neszbeqi/cle3-pt-dashboard"} > "%~dp0agent_config.json"
echo.
echo  GitHub sync configured.

REM Run the standard setup
echo  Running standard setup...
call "%~dp0setup.bat"

echo.
echo  ================================================
echo   Setup complete!
echo.
echo   Your machine is now a shared server.
echo   The dashboard will sync data to GitHub
echo   automatically whenever you are logged in.
echo.
echo   BOOKMARK THIS URL - it always works:
echo   https://neszbeqi.github.io/cle3-pt-dashboard
echo.
echo   When you are online: full dashboard at
echo   http://localhost:5050 (or share your IP)
echo.
echo   When no one is online: GitHub Pages shows
echo   the last known data.
echo  ================================================
echo.
pause
