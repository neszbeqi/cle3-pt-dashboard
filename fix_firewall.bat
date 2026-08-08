@echo off
:: This file must be run as Administrator
:: Right-click -> "Run as administrator"
echo Adding Windows Firewall rule for CLE3 PT Dashboard (port 5050)...
netsh advfirewall firewall delete rule name="CLE3 PT Dashboard" >nul 2>&1
netsh advfirewall firewall add rule name="CLE3 PT Dashboard" dir=in action=allow protocol=TCP localport=5050
if %errorlevel%==0 (
    echo.
    echo SUCCESS - Other AMs on the same network can now reach this server.
    echo They can access it at the URL shown in the dashboard header.
) else (
    echo.
    echo FAILED - Try running this file again by right-clicking and choosing Run as administrator.
)
echo.
pause