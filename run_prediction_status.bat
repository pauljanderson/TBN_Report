@echo off
rem Refresh the prediction job status page. Does not start or stop anything.
setlocal EnableExtensions
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1
"%PY%" -u "%~dp0tools\prediction_job_control.py" status
echo.
pause
exit /b %errorlevel%
