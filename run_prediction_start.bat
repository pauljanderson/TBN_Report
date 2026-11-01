@echo off
rem Start a missing prediction supervisor and/or catalog scan. Leave one that is already up.
setlocal EnableExtensions
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1
"%PY%" -u "%~dp0tools\prediction_job_control.py" start
echo.
pause
exit /b %errorlevel%
