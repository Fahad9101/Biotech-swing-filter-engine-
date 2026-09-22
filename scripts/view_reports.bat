@echo off
REM Pulls the latest committed reports from main and opens both HTML
REM reports directly from disk in your default browser.
REM
REM This exists because GitHub's own web UI deliberately does not render
REM .html files inline (shows raw source instead, for security reasons) -
REM opening the local file bypasses that entirely and always shows the
REM real, rendered page. Double-click this file any time you want the
REM current reports; it is safe to run as often as you like.

setlocal
cd /d "%~dp0\.."

echo Pulling the latest reports from main...
git pull origin main --ff-only
if errorlevel 1 (
    echo.
    echo Could not pull the latest changes. Check your internet connection,
    echo make sure you have no conflicting local changes, and try again.
    echo.
    pause
    exit /b 1
)

set OPENED=0

if exist "reports\watchlist.html" (
    start "" "reports\watchlist.html"
    set OPENED=1
) else (
    echo reports\watchlist.html not found yet - it appears after the first
    echo scan run.
)

if exist "reports\forward-log\forward-log.html" (
    start "" "reports\forward-log\forward-log.html"
    set OPENED=1
) else (
    echo reports\forward-log\forward-log.html not found yet - it appears after
    echo the first run that logs a shortlist entry.
)

if "%OPENED%"=="0" (
    echo.
    echo No reports found yet. Has the "Catalyst filter scan" workflow run?
    pause
)

endlocal
