@echo off
set /p CITY=Enter city name:
setlocal
cd /d "%~dp0"
python -u Scripts/sunmap.py "%CITY%\Data\clipped_suburbs_dsm.tif" --out "%CITY%\Data\winter_sun.tif"
if %errorlevel% neq 0 (
    echo [%time%] ERROR: script failed with code %errorlevel%
    pause
    exit /b %errorlevel%
)

echo [%time%] Script finished.
pause