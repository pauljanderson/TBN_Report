@echo off
rem Rebuild orders_performance.html + dashboard.html from the local tape.
rem Code on main (git pull) does NOT rewrite these HTML stamps by itself.
rem After merging dashboard/writer fixes (Size @ price, Gibson poly invert, …),
rem ALWAYS git_pull.bat FIRST — this file only exists on disk after pull —
rem then double-click this (or let git_pull.bat call it).
rem Does not place, cancel, or sell.
rem
rem If this bat is missing ("not recognized"): you have not pulled yet.
rem   git pull origin main
rem   OR one-liner: python tools\write_orders_performance.py

setlocal EnableExtensions
cd /d "%~dp0"

echo.
echo === kitchen dashboard rebuild ===
echo Repo: %CD%
echo If this bat was "not recognized", run: git pull origin main
echo Python fallback (same writer): python tools\write_orders_performance.py
echo.

set "ORDERS=local\paul_experiments\prediction_market_arb_exhaustive_20261017\raw\orders.jsonl"
if not exist "%ORDERS%" (
  echo Missing local tape: %ORDERS%
  echo This PC has no orders.jsonl — cannot rebuild the kitchen stamp here.
  echo On the trading PC with tape, re-run this bat after git pull.
  echo Fallback after pull: python tools\write_orders_performance.py
  exit /b 1
)

if not defined PY call "%~dp0resolve_python.bat"
echo === python tools/write_orders_performance.py ===
echo Rewrites:
echo   - local\...\raw\orders_performance.html
echo   - drive\...\dashboard.html  (via write_from_performance)
echo.

if defined PY (
  "%PY%" -u tools\write_orders_performance.py
) else (
  python -u tools\write_orders_performance.py
)
set ERR=%ERRORLEVEL%
if not "%ERR%"=="0" (
  echo Rebuild failed exit=%ERR%
  echo Retry: python tools\write_orders_performance.py
  exit /b %ERR%
)

echo.
echo === dashboard stamp gate (Size @ price / Gibson) ===
if defined PY (
  "%PY%" -u tools\dashboard_stamp_gate.py --require-stamp
) else (
  python -u tools\dashboard_stamp_gate.py --require-stamp
)
set GATE=%ERRORLEVEL%

echo.
echo === paths written (stamp) ===
echo orders_performance: local\paul_experiments\prediction_market_arb_exhaustive_20261017\raw\orders_performance.html
echo dashboard.html:     drive stamp ^(see "wrote ..." lines above^)
echo If bat missing next time: git pull origin main
echo Then: python tools\write_orders_performance.py
exit /b %GATE%
