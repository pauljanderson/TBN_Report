@echo off
rem Regenerate TBN New Systems away-status HTML for Drive / phone viewing.
rem Outputs:
rem   drive\paul_experiments\tbn_new_systems\AWAY_STATUS.html
rem   drive\TBN_New_Systems_AWAY_STATUS.html
rem Also patches STATUS.html with a remote-viewing link when missing.
setlocal EnableExtensions
cd /d "%~dp0"
set "PY=python"
if exist "%LocalAppData%\Programs\Python\Python310\python.exe" set "PY=%LocalAppData%\Programs\Python\Python310\python.exe"
"%PY%" tools\update_tbn_away_status.py %*
exit /b %errorlevel%
