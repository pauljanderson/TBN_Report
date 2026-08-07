@echo off
rem Gap-up scanner — Open[t] > Close[t-1] across data\newdata\data\*.csv (excl. SPY).
rem Script: tools\scan_gap_ups.py
rem Outputs: drive\GapUp_Scan_<stamp>.csv + sortable .html twin
rem Forward rets: RET_C_ND / RET_O_ND for horizons (default 5,10,15,20)
rem
rem How to run:
rem   run_gap_up_scan.bat
rem   run_gap_up_scan.bat --symbols AAPL,NVDA,TSLA --min-gap-pct 2
rem   (optional) set GAP_SYMBOLS=AAPL,NVDA & run_gap_up_scan.bat
rem
rem EDIT DEFAULTS HERE — save, then run. Env override still works if already set.
rem Extra CLI args (%*) are forwarded after the defaults below.

setlocal EnableExtensions
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

rem === EDIT DEFAULTS HERE ===
if not defined GAP_MIN_PCT set "GAP_MIN_PCT=2.0"
rem Leave GAP_MIN_VS_PREV_HIGH empty to disable; set 0 to require open > prev high
if not defined GAP_MIN_VS_PREV_HIGH set "GAP_MIN_VS_PREV_HIGH="
rem Empty = all CSVs except SPY
if not defined GAP_SYMBOLS set "GAP_SYMBOLS="
if not defined GAP_START set "GAP_START="
if not defined GAP_END set "GAP_END="
if not defined GAP_DATA_DIR set "GAP_DATA_DIR=data\newdata\data"
rem Forward trading-day horizons for RET_C_ND / RET_O_ND
if not defined GAP_HORIZONS set "GAP_HORIZONS=5,10,15,20"
rem Empty = drive\GapUp_Scan_<stamp>.csv
if not defined GAP_OUT set "GAP_OUT="
rem === END EDIT DEFAULTS ===

set "EXTRA="
if defined GAP_SYMBOLS if not "%GAP_SYMBOLS%"=="" set "EXTRA=%EXTRA% --symbols %GAP_SYMBOLS%"
if defined GAP_START if not "%GAP_START%"=="" set "EXTRA=%EXTRA% --start-date %GAP_START%"
if defined GAP_END if not "%GAP_END%"=="" set "EXTRA=%EXTRA% --end-date %GAP_END%"
if defined GAP_MIN_VS_PREV_HIGH if not "%GAP_MIN_VS_PREV_HIGH%"=="" set "EXTRA=%EXTRA% --min-gap-vs-prev-high %GAP_MIN_VS_PREV_HIGH%"
if defined GAP_HORIZONS if not "%GAP_HORIZONS%"=="" set "EXTRA=%EXTRA% --horizons %GAP_HORIZONS%"
if defined GAP_OUT if not "%GAP_OUT%"=="" set "EXTRA=%EXTRA% --out %GAP_OUT%"

echo [GAP] min_gap_pct=%GAP_MIN_PCT% symbols=%GAP_SYMBOLS% start=%GAP_START% end=%GAP_END% horizons=%GAP_HORIZONS%
"%PY%" "%~dp0tools\scan_gap_ups.py" --data-dir "%GAP_DATA_DIR%" --min-gap-pct %GAP_MIN_PCT% %EXTRA% %*
exit /b %errorlevel%
