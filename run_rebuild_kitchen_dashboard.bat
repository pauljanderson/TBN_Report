@echo off
rem Rebuild orders_performance.html + dashboard.html from the local tape.
rem Code on main (git pull) does NOT rewrite these HTML stamps by itself.
rem After merging dashboard/writer fixes (Size @ price, Gibson poly invert, …),
rem double-click this on the trading PC (or let git_pull.bat call it).
rem Does not place, cancel, or sell.

setlocal EnableExtensions
cd /d "%~dp0"

set "ORDERS=local\paul_experiments\prediction_market_arb_exhaustive_20261017\raw\orders.jsonl"
if not exist "%ORDERS%" (
  echo Missing local tape: %ORDERS%
  echo This PC has no orders.jsonl — cannot rebuild the kitchen stamp here.
  echo On the trading PC with tape, re-run this bat after git pull.
  exit /b 1
)

if not defined PY call "%~dp0resolve_python.bat"
echo === python tools/write_orders_performance.py ===
echo (also rewrites drive\...\dashboard.html via write_from_performance)
echo.

if defined PY (
  "%PY%" -u tools\write_orders_performance.py
) else (
  python -u tools\write_orders_performance.py
)
set ERR=%ERRORLEVEL%
if not "%ERR%"=="0" (
  echo Rebuild failed exit=%ERR%
  exit /b %ERR%
)

echo.
echo === dashboard stamp gate (Size @ price / Gibson) ===
if defined PY (
  "%PY%" -u tools\dashboard_stamp_gate.py --require-stamp
) else (
  python -u tools\dashboard_stamp_gate.py --require-stamp
)
exit /b %ERRORLEVEL%
