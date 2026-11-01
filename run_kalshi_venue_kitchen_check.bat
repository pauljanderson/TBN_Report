@echo off
rem Kalshi venue-vs-kitchen gap + same-direction stack check.
rem Prefers the latest Drive dump from run_kalshi_recon_dump.bat.
rem Does not place, cancel, or sell.

setlocal
cd /d "%~dp0"

set DUMP=
if exist "drive\paul_experiments\prediction_market_arb_exhaustive_20261017\kalshi_recon_dump\kalshi_recon_dump_latest.json" (
  set "DUMP=drive\paul_experiments\prediction_market_arb_exhaustive_20261017\kalshi_recon_dump\kalshi_recon_dump_latest.json"
) else if exist "local\paul_experiments\prediction_market_arb_exhaustive_20261017\raw\kalshi_recon_dump\kalshi_recon_dump_latest.json" (
  set "DUMP=local\paul_experiments\prediction_market_arb_exhaustive_20261017\raw\kalshi_recon_dump\kalshi_recon_dump_latest.json"
)

if "%DUMP%"=="" (
  echo MISSING dump. Run run_kalshi_recon_dump.bat first.
  exit /b 2
)

rem Optional: pass kitchen Kalshi-closed P&amp;L as first arg, e.g. -0.90
set KITCHEN=%~1
if "%KITCHEN%"=="" (
  python -u tools\kalshi_venue_kitchen_check.py --dump "%DUMP%"
) else (
  python -u tools\kalshi_venue_kitchen_check.py --dump "%DUMP%" --kitchen-pnl %KITCHEN%
)
exit /b %ERRORLEVEL%
