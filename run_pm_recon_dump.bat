@echo off
rem Read-only multi-venue PM dump (Kalshi + Polymarket + Gemini + Novig).
rem Uses secrets on this PC. Writes Drive + local pm_recon_dump JSON.
rem Does not place, cancel, or sell.

setlocal
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 (
  python -u tools\dump_pm_recon.py %*
  exit /b %ERRORLEVEL%
)
"%PY%" -u tools\dump_pm_recon.py %*
exit /b %ERRORLEVEL%
