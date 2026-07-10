@echo off
rem MTS sheet-parity backtest — official universe (stock_analysis\mts_universe.py)
rem Outputs MTS_Closed|Open|Scanner|Watchlist|Report|Summary_<ts>.csv in drive\
rem Params: band_pct=0.018 (manual override of optimizer 0.016)
setlocal EnableExtensions
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

rem Allow DailyRun override: set MTS_SYMBOLS before calling this script
if defined MTS_SYMBOLS goto :have_mts_symbols
set "MTS_SYM_FILE=%TEMP%\mts_symbols_run.txt"
"%PY%" "%~dp0stock_analysis\print_mts_symbols.py" > "%MTS_SYM_FILE%" 2>nul
if exist "%MTS_SYM_FILE%" set /p MTS_SYMBOLS=<"%MTS_SYM_FILE%"
if exist "%MTS_SYM_FILE%" del "%MTS_SYM_FILE%" >nul 2>&1
:have_mts_symbols
if not defined MTS_SYMBOLS (
  echo ERROR: MTS_SYMBOLS empty - check print_mts_symbols.py>&2
  exit /b 1
)

"%PY%" stock_analysis\rocket_brt.py data\newdata\data -o drive -w 4 --no-regression --mts-sheet-parity -v band_pct=0.018 -v touch_threshold=2 -v strong_post_pivot_bars=7 -v strong_post_pivot_pct=0.06 -v strong_pre_pivot_bars=7 -v strong_pre_pivot_pct=0.12 -v target_pct=1.22 -v stop_pct=0.934 -v stop_pct_is_multiplier=true -v stop_anchor=signal_low -s "%MTS_SYMBOLS%"
if errorlevel 1 exit /b 1
call "%~dp0run_copy_latest.bat"
exit /b %errorlevel%
