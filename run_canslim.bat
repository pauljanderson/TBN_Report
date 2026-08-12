@echo off
rem William O'Neil CAN SLIM — price-legs v0 (prefix CS_)
rem Engine: stock_analysis\rocket_oneil_canslim.py (standalone; not rocket_tbn mode)
rem Docs: drive\paul_experiments\tbn_new_systems\oneil_canslim\HOW_TO_RUN.html
rem
rem RUNNABLE: N (near 52w high + pivot), S (volume), L (RS proxy), M (SPY / optional MM)
rem STUBS:    C (EPS YoY), A (annual EPS/ROE), I (sponsorship) — no fundamentals feed
rem
rem Universe: drive\universes\CS_universe.csv (default * = full scan / omit -s)
rem Override: run_canslim.bat path\to\test_universe.csv
rem          set CS_UNIVERSE_CSV=...
rem          set CS_SYMBOLS=NVDA,TSLA,AMD
rem Full universe (all data\newdata\data\*.csv) — no env vars:
rem   run_canslim.bat ALL
rem   run_canslim.bat --all
rem   run_canslim.bat "*"          (quote * in PowerShell; bare * often expands)
rem Legacy env: set CS_SYMBOLS=* / ALL / set CS_ALL_CSV=1
rem Extra CLI: trailing %* forwarded to Python (leading .csv / ALL stripped; flags kept).
rem   run_canslim.bat --rs-min 70
rem
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1
if not defined CS_TARGET set "CS_TARGET=1.20"
if not defined CS_STOP set "CS_STOP=0.92"
if not defined CS_RS_MIN set "CS_RS_MIN=80"
if not defined CS_PIVOT_LB set "CS_PIVOT_LB=55"
if not defined CS_VOL_MULT set "CS_VOL_MULT=1.40"
if not defined CS_MAX_BELOW_52W set "CS_MAX_BELOW_52W=0.25"
if not defined CS_MARKET_GATE set "CS_MARKET_GATE=true"
if not defined CS_MM_GATE set "CS_MM_GATE=false"
if not defined CS_MAX_POSITIONS set "CS_MAX_POSITIONS=0"
if not defined CS_AGGRESSIVE set "CS_AGGRESSIVE=true"
set "CS_AGG_FLAG="
if /i "%CS_AGGRESSIVE%"=="true" set "CS_AGG_FLAG=--aggressive"
if /i "%CS_AGGRESSIVE%"=="1" set "CS_AGG_FLAG=--aggressive"
if /i "%CS_AGGRESSIVE%"=="yes" set "CS_AGG_FLAG=--aggressive"

call "%~dp0tools\apply_universe_cli_arg.bat" CS_UNIV_ARG %1 %2
call "%~dp0tools\build_cli_forward.bat" CS_FORWARD "%CS_UNIV_ARG%" %*
call "%~dp0tools\load_universe_csv.bat" CS "%CS_UNIV_ARG%"
if errorlevel 1 exit /b 1
echo [CS] Universe src=%CS_UNIVERSE_SRC% pass_s=%CS_PASS_SYMBOLS%

echo [CS] CAN SLIM price-legs — rocket_oneil_canslim.py (C/A/I=STUB)
if "%CS_PASS_SYMBOLS%"=="1" (
  "%PY%" stock_analysis\rocket_oneil_canslim.py data\newdata\data -o drive ^
    --initial-capital 500000 --aggressive-max-multiple 2.0 --margin-utilization 0.6 ^
    --target-pct %CS_TARGET% --stop-pct %CS_STOP% ^
    --rs-min %CS_RS_MIN% --pivot-lookback %CS_PIVOT_LB% --vol-breakout-mult %CS_VOL_MULT% ^
    --max-pct-below-52w-high %CS_MAX_BELOW_52W% ^
    --market-gate %CS_MARKET_GATE% --mm-gate %CS_MM_GATE% ^
    --max-positions %CS_MAX_POSITIONS% %CS_AGG_FLAG% ^
    -s "!CS_SYMBOLS!" ^
    !CS_FORWARD!
) else (
  "%PY%" stock_analysis\rocket_oneil_canslim.py data\newdata\data -o drive ^
    --initial-capital 500000 --aggressive-max-multiple 2.0 --margin-utilization 0.6 ^
    --target-pct %CS_TARGET% --stop-pct %CS_STOP% ^
    --rs-min %CS_RS_MIN% --pivot-lookback %CS_PIVOT_LB% --vol-breakout-mult %CS_VOL_MULT% ^
    --max-pct-below-52w-high %CS_MAX_BELOW_52W% ^
    --market-gate %CS_MARKET_GATE% --mm-gate %CS_MM_GATE% ^
    --max-positions %CS_MAX_POSITIONS% %CS_AGG_FLAG% ^
    !CS_FORWARD!
)
exit /b %errorlevel%
