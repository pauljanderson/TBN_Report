@echo off
rem Show live systems A-E (on/off, stake, max, pid). Extra args turn a system on or off.
setlocal EnableExtensions
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1
"%PY%" -u "%~dp0tools\prediction_job_control.py" systems %*
echo.
pause
exit /b %errorlevel%
