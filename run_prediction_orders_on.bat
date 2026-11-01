@echo off
rem Turn Lock gap (A) back on after a one-leg fill.
rem Does not stop Tennis crossover / C / D / E.
rem Does not start a second live_strategy_b.py.
rem Does not sell tickets.
setlocal EnableExtensions
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1
"%PY%" -u "%~dp0tools\prediction_job_control.py" systems --lock on
echo.
pause
exit /b %errorlevel%
