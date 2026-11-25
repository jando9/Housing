@echo off
setlocal
cd /d "%~dp0"
python sunmap.py "..\Data\new-zealand-lidar-1m-dsm\clipped_suburbs_DSM.tif" --dem "..\Data\new-zealand-lidar-1m-dem\clipped_suburbs_DEM.tif" --out "..\winter_sun.tif"