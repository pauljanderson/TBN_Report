@echo off
rem All-platform venue-vs-kitchen check: kalshi, polymarket, gemini, novig.
rem Prefers pm_recon_dump, falls back to kalshi dump, kitchen HTML, settled_pnl.
rem Does not place, cancel, or sell.

setlocal EnableExtensions
cd /d "%~dp0"

set HTML=
if exist "drive\paul_experiments\prediction_market_arb_exhaustive_20261017\orders_performance.html" (
  set "HTML=drive\paul_experiments\prediction_market_arb_exhaustive_20261017\orders_performance.html"
)

set SETTLED=
if exist "local\paul_experiments\prediction_market_arb_exhaustive_20261017\raw\settled_pnl.json" (
  set "SETTLED=local\paul_experiments\prediction_market_arb_exhaustive_20261017\raw\settled_pnl.json"
)

set PMDUMP=
if exist "drive\paul_experiments\prediction_market_arb_exhaustive_20261017\pm_recon_dump\pm_recon_dump_latest.json" (
  set "PMDUMP=drive\paul_experiments\prediction_market_arb_exhaustive_20261017\pm_recon_dump\pm_recon_dump_latest.json"
) else if exist "local\paul_experiments\prediction_market_arb_exhaustive_20261017\raw\pm_recon_dump\pm_recon_dump_latest.json" (
  set "PMDUMP=local\paul_experiments\prediction_market_arb_exhaustive_20261017\raw\pm_recon_dump\pm_recon_dump_latest.json"
)

set KDUMP=
if exist "drive\paul_experiments\prediction_market_arb_exhaustive_20261017\kalshi_recon_dump\kalshi_recon_dump_latest.json" (
  set "KDUMP=drive\paul_experiments\prediction_market_arb_exhaustive_20261017\kalshi_recon_dump\kalshi_recon_dump_latest.json"
) else if exist "local\paul_experiments\prediction_market_arb_exhaustive_20261017\raw\kalshi_recon_dump\kalshi_recon_dump_latest.json" (
  set "KDUMP=local\paul_experiments\prediction_market_arb_exhaustive_20261017\raw\kalshi_recon_dump\kalshi_recon_dump_latest.json"
)

set ARGS=
if not "%HTML%"=="" set ARGS=%ARGS% --kitchen-html "%HTML%"
if not "%SETTLED%"=="" set ARGS=%ARGS% --settled-pnl "%SETTLED%"
if not "%PMDUMP%"=="" set ARGS=%ARGS% --pm-dump "%PMDUMP%"
if not "%KDUMP%"=="" set ARGS=%ARGS% --kalshi-dump "%KDUMP%"

rem Optional first arg: Kalshi window kitchen closed P&L (e.g. -0.90)
if not "%~1"=="" set ARGS=%ARGS% --kitchen-pnl %~1

rem Trading-PC default: require a dump section for every shop.
set ARGS=%ARGS% --require-all-dumps

if "%HTML%"=="" if "%SETTLED%"=="" if "%PMDUMP%"=="" if "%KDUMP%"=="" (
  echo MISSING inputs. Run run_pm_recon_dump.bat and/or sync orders_performance.html.
  exit /b 2
)

if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 (
  python -u tools\pm_venue_kitchen_check.py %ARGS%
  exit /b %ERRORLEVEL%
)
"%PY%" -u tools\pm_venue_kitchen_check.py %ARGS%
exit /b %ERRORLEVEL%
