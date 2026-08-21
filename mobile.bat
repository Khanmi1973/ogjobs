@echo off
REM Opens the dashboard so your PHONE can reach it over the same Wi-Fi.
REM
REM The console will print a link like:
REM     http://192.168.1.20:8765/?k=AbC123xyz
REM Type that into your phone's browser once - the key is remembered.
REM
REM Anyone on the same Wi-Fi who has that link can use the dashboard,
REM so only run this on a network you trust, and close this window when done.

cd /d "%~dp0"

echo.
echo   Starting the dashboard in Wi-Fi mode...
echo   Look for the phone link below, then type it into your phone's browser.
echo   Leave this window open. Press Ctrl+C here to stop.
echo.

python -m ogjobs serve --host lan --port 8765 --no-open

if errorlevel 1 (
    echo.
    echo Could not start. If the port is busy try:
    echo    python -m ogjobs serve --host lan --port 8790
    pause
)
