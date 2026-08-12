@echo off
rem Zone exits A/B: static target/stop vs nearest-zone target/stop (+ RR 2/3/4).
rem Forwards trailing -v via the Python runner --extra-v if needed.
rem   run_zone_exits_ab.bat
rem   run_zone_exits_ab.bat --systems BRT,YH --jobs 2
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1
"%PY%" tools\run_zone_exits_ab.py %*
exit /b %errorlevel%
