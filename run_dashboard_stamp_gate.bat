@echo off
rem Fail when living dashboard.html lags writer columns (Size @ price / Gibson).
rem Prefer after rebuild / before claiming a merge is "on the dashboard".
rem Does not place, cancel, or sell.

setlocal EnableExtensions
cd /d "%~dp0"

if not defined PY call "%~dp0resolve_python.bat"
if defined PY (
  "%PY%" -u tools\dashboard_stamp_gate.py --require-stamp %*
) else (
  python -u tools\dashboard_stamp_gate.py --require-stamp %*
)
exit /b %ERRORLEVEL%
