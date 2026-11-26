@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
python Scripts/load_shortlist_updated.py shortlist.csv > load_log.txt 2>&1
set "EXIT_CODE=%ERRORLEVEL%"
type load_log.txt
echo.
echo Exit code: %EXIT_CODE%
pause
