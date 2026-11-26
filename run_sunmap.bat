@echo off
set /p CITY=Enter city name:
setlocal
cd /d "%~dp0"
python sunmap.py "%CITY%\Data\new-zealand-lidar-1m-dsm\clipped_suburbs_DSM.tif" --out "%CITY%\Data\winter_sun.tif"