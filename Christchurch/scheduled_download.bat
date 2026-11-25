@echo off
for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
    if /I not "%%A"=="PASSWORD" set "%%A=%%B"
)
curl -L "%EXCEL_URL%" -o "%LOCAL_CSV%"
call Christchurch/run_load_shortlist.bat