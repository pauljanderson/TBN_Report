@echo off
rem Stop the prediction supervisor, its live pollers, and the catalog scan, then start one of each.
setlocal EnableExtensions
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1
"%PY%" -u "%~dp0tools\prediction_job_control.py" restart
echo.
pause
exit /b %errorlevel%
