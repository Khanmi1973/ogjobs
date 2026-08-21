@echo off
REM Opens the live Oil & Gas Job Radar dashboard in your browser.
REM The "Scan now" button on the page fetches fresh jobs from every source.
REM Keep this window open while you use the dashboard; close it or press
REM Ctrl+C to shut the dashboard down.

cd /d "%~dp0"

echo.
echo   Starting the Oil ^& Gas Job Radar dashboard...
echo   Your browser will open at http://127.0.0.1:8765/
echo   Leave this window open. Press Ctrl+C here to stop.
echo.

python -m ogjobs serve --port 8765

if errorlevel 1 (
    echo.
    echo Could not start the dashboard.
    echo If the port is busy, try:  python -m ogjobs serve --port 8790
    pause
)
