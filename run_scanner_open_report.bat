@echo off
rem Run at/after 9:30 AM ET: Yahoo Finance opens for scanner symbols -> BUY vs IGNORE report.
setlocal EnableExtensions
cd /d "%~dp0"
if not defined PY (
  for /f "delims=" %%P in ('where python 2^>nul') do set "PY=%%P" & goto :py_ok
  echo ERROR: set PY to your python.exe or add python to PATH.>&2
  exit /b 1
)
:py_ok
"%PY%" "%~dp0generate_scanner_open_report.py" --drive drive --wait-for-open %*
exit /b %errorlevel%
