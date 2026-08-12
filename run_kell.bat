@echo off
rem Oliver Kell — Price Action Cycle (PAC) / Wedge Pop — standalone research runner
rem Engine: stock_analysis\rocket_kell_pac.py  (does NOT edit rocket_tbn)
rem Outputs: drive\KELL_*_<ts>.csv
rem Docs: drive\paul_experiments\tbn_new_systems\kell_pac\HOW_TO_RUN.html
rem
rem Universe: drive\universes\KELL_universe.csv (default * = full scan / omit -s)
rem Override: run_kell.bat path\to\test_universe.csv
rem          set KELL_UNIVERSE_CSV=...
rem          set KELL_SYMBOLS=AAPL,MSFT
rem Full universe (all data\newdata\data\*.csv) — no env vars:
rem   run_kell.bat ALL
rem   run_kell.bat --all
rem   run_kell.bat "*"          (quote * in PowerShell; bare * often expands)
rem Legacy env: set KELL_SYMBOLS=* / ALL / set KELL_ALL_CSV=1
rem Extra CLI: trailing %* forwarded to rocket_kell_pac.py (leading .csv / ALL stripped; flags kept).
rem   run_kell.bat --kell-trail-ema 15

setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

if not defined KELL_TRAIL_EMA set "KELL_TRAIL_EMA=20"
if not defined KELL_TIGHT_PCT set "KELL_TIGHT_PCT=0.025"
if not defined KELL_REV_EXT_PCT set "KELL_REV_EXT_PCT=0.08"
if not defined KELL_EXH_BAN_PCT set "KELL_EXH_BAN_PCT=0.12"
if not defined KELL_AGGRESSIVE set "KELL_AGGRESSIVE=true"
if not defined KELL_MAX_POSITIONS set "KELL_MAX_POSITIONS=0"

set "KELL_AGG_FLAG="
if /i "%KELL_AGGRESSIVE%"=="true" set "KELL_AGG_FLAG=--aggressive"
if /i "%KELL_AGGRESSIVE%"=="1" set "KELL_AGG_FLAG=--aggressive"
if /i "%KELL_AGGRESSIVE%"=="yes" set "KELL_AGG_FLAG=--aggressive"

call "%~dp0tools\apply_universe_cli_arg.bat" KELL_UNIV_ARG %1 %2
call "%~dp0tools\build_cli_forward.bat" KELL_FORWARD "%KELL_UNIV_ARG%" %*
call "%~dp0tools\load_universe_csv.bat" KELL "%KELL_UNIV_ARG%"
if errorlevel 1 exit /b 1
echo [KELL] Universe src=%KELL_UNIVERSE_SRC% pass_s=%KELL_PASS_SYMBOLS%

echo [KELL] standalone rocket_kell_pac.py ^(Wedge Pop v0 research^)
if "%KELL_PASS_SYMBOLS%"=="1" (
  "%PY%" stock_analysis\rocket_kell_pac.py data\newdata\data -o drive %KELL_AGG_FLAG% ^
    --initial-capital 500000 --aggressive-max-multiple 2.0 --margin-utilization 0.6 ^
    --max-positions %KELL_MAX_POSITIONS% ^
    --kell-trail-ema %KELL_TRAIL_EMA% ^
    --kell-tight-pct %KELL_TIGHT_PCT% ^
    --kell-rev-ext-pct %KELL_REV_EXT_PCT% ^
    --kell-exh-ban-pct %KELL_EXH_BAN_PCT% ^
    -s "!KELL_SYMBOLS!" ^
    !KELL_FORWARD!
) else (
  "%PY%" stock_analysis\rocket_kell_pac.py data\newdata\data -o drive %KELL_AGG_FLAG% ^
    --initial-capital 500000 --aggressive-max-multiple 2.0 --margin-utilization 0.6 ^
    --max-positions %KELL_MAX_POSITIONS% ^
    --kell-trail-ema %KELL_TRAIL_EMA% ^
    --kell-tight-pct %KELL_TIGHT_PCT% ^
    --kell-rev-ext-pct %KELL_REV_EXT_PCT% ^
    --kell-exh-ban-pct %KELL_EXH_BAN_PCT% ^
    !KELL_FORWARD!
)
exit /b %errorlevel%
