@echo off
REM ogjobs - scan every enabled source and refresh the report.
REM Schedule this daily with:
REM   schtasks /create /tn "OG Job Radar" /tr "C:\cdx\ogjobs\run.bat" /sc daily /st 07:00

cd /d "%~dp0"

echo.
echo ============================================
echo   Oil ^& Gas Job Radar - starting scan
echo   %DATE% %TIME%
echo ============================================
echo.

python -m ogjobs run

if errorlevel 1 (
    echo.
    echo Scan finished with errors. Run this to see details:
    echo    set OGJOBS_DEBUG=1 ^&^& python -m ogjobs run
    pause
    exit /b 1
)

echo.
echo Report ready: %CD%\data\reports\jobs.html
start "" "%CD%\data\reports\jobs.html"
