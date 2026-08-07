@echo off
rem Qullamaggie EP / HTF — STANDALONE (no rocket_tbn)
rem Engine: stock_analysis\rocket_qull_ep_htf.py
rem Host/TBN path: run_qull.bat → run_qullamaggie_htf.bat (requires qull_mode)
rem Docs: drive\paul_experiments\tbn_new_systems\qull_ep_htf\HOW_TO_RUN.html
rem
rem Universe: drive\universes\QULL_universe.csv (default * = full scan)
rem Override: run_qull_standalone.bat path\to\test_universe.csv
rem          set QULL_UNIVERSE_CSV=...
rem          set QULL_SYMBOLS=AAPL,MSFT
rem Full universe (all data\newdata\data\*.csv) — no env vars:
rem   run_qull_standalone.bat ALL
rem   run_qull_standalone.bat --all
rem   run_qull_standalone.bat "*"   (quote * in PowerShell; bare * often expands)
rem Legacy env: set QULL_SYMBOLS=* / ALL / set QULL_ALL_CSV=1
rem Extra CLI (%*) forwarded to python module (except leading .csv / ALL override).

setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

if not defined QULL_SETUP set "QULL_SETUP=htf"
if not defined QULL_PRIOR_RUN set "QULL_PRIOR_RUN=0.50"
if not defined QULL_PRIOR_BARS set "QULL_PRIOR_BARS=42"
if not defined QULL_COIL_BARS set "QULL_COIL_BARS=10"
if not defined QULL_COIL_RANGE set "QULL_COIL_RANGE=0.15"
if not defined QULL_TRAIL_EMA set "QULL_TRAIL_EMA=10"
if not defined QULL_BO_VOL set "QULL_BO_VOL=1.5"
if not defined QULL_MARKET set "QULL_MARKET=true"
if not defined QULL_MAX_STOP_ADR set "QULL_MAX_STOP_ADR=1.0"
if not defined QULL_MAX_POSITIONS set "QULL_MAX_POSITIONS=0"
if not defined QULL_AGGRESSIVE set "QULL_AGGRESSIVE=true"
if not defined QULL_MIN_PRICE set "QULL_MIN_PRICE=3"
if not defined QULL_MIN_ADV set "QULL_MIN_ADV=2000000"

call "%~dp0tools\apply_universe_cli_arg.bat" QULL_UNIV_ARG %1 %2
set "QULL_FORWARD=%*"
if not "%QULL_UNIV_ARG%"=="" set "QULL_FORWARD="
call "%~dp0tools\load_universe_csv.bat" QULL "%QULL_UNIV_ARG%"
if errorlevel 1 exit /b 1
echo [QULL-SA] Universe src=%QULL_UNIVERSE_SRC% pass_s=%QULL_PASS_SYMBOLS%

set "QULL_AGG_FLAG="
if /i "%QULL_AGGRESSIVE%"=="true" set "QULL_AGG_FLAG=--aggressive"
if /i "%QULL_AGGRESSIVE%"=="1" set "QULL_AGG_FLAG=--aggressive"
if /i "%QULL_AGGRESSIVE%"=="yes" set "QULL_AGG_FLAG=--aggressive"

echo [QULL-SA] rocket_qull_ep_htf.py setup=%QULL_SETUP% trail=EMA%QULL_TRAIL_EMA%

if "%QULL_PASS_SYMBOLS%"=="1" (
  "%PY%" stock_analysis\rocket_qull_ep_htf.py data\newdata\data -o drive %QULL_AGG_FLAG% ^
    --setup %QULL_SETUP% ^
    --prior-run %QULL_PRIOR_RUN% --prior-bars %QULL_PRIOR_BARS% ^
    --coil-bars %QULL_COIL_BARS% --coil-range %QULL_COIL_RANGE% ^
    --trail-ema %QULL_TRAIL_EMA% --bo-vol %QULL_BO_VOL% ^
    --market-filter %QULL_MARKET% --max-stop-adr %QULL_MAX_STOP_ADR% ^
    --min-price %QULL_MIN_PRICE% --min-adv %QULL_MIN_ADV% ^
    --max-positions %QULL_MAX_POSITIONS% ^
    -s "!QULL_SYMBOLS!" ^
    !QULL_FORWARD!
) else (
  "%PY%" stock_analysis\rocket_qull_ep_htf.py data\newdata\data -o drive %QULL_AGG_FLAG% ^
    --setup %QULL_SETUP% ^
    --prior-run %QULL_PRIOR_RUN% --prior-bars %QULL_PRIOR_BARS% ^
    --coil-bars %QULL_COIL_BARS% --coil-range %QULL_COIL_RANGE% ^
    --trail-ema %QULL_TRAIL_EMA% --bo-vol %QULL_BO_VOL% ^
    --market-filter %QULL_MARKET% --max-stop-adr %QULL_MAX_STOP_ADR% ^
    --min-price %QULL_MIN_PRICE% --min-adv %QULL_MIN_ADV% ^
    --max-positions %QULL_MAX_POSITIONS% ^
    -s "*" ^
    !QULL_FORWARD!
)
exit /b %errorlevel%
