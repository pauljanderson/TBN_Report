@echo off
rem MTS sheet-parity backtest — outputs MTS_Closed|Open|Scanner|Watchlist|Report|Summary_<ts>.csv in drive\
rem Standalone: double-click or call from DailyRun.
rem Universe: drive\universes\MTS_universe.csv (one ticker per line)
rem Override: run_mts.bat path\to\test_universe.csv
rem          set MTS_UNIVERSE_CSV=...
rem          set MTS_SYMBOLS=AAPL,MSFT
rem Full universe (all data\newdata\data\*.csv) — no env vars:
rem   run_mts.bat ALL
rem   run_mts.bat --all
rem   run_mts.bat "*"          (quote * in PowerShell; bare * often expands)
rem Legacy env: set MTS_SYMBOLS=* / ALL / set MTS_ALL_CSV=1
rem IND_TC_* on Closed: add -v use_indicators=true (report-only; keep indicator_buy=off for no gates).
rem SSoT: drive\universes\MTS_universe.csv (also read by stock_analysis\mts_universe.py).
rem Params: band_pct=0.018 (manual override of optimizer 0.016)
rem Extra CLI: trailing %* forwarded to rocket_tbn (leading .csv / ALL stripped; -v kept).
rem   run_mts.bat -v band_pct=0.016
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

call "%~dp0tools\apply_universe_cli_arg.bat" MTS_UNIV_ARG %1 %2
call "%~dp0tools\build_cli_forward.bat" MTS_FORWARD "%MTS_UNIV_ARG%" %*
call "%~dp0tools\load_universe_csv.bat" MTS "%MTS_UNIV_ARG%"
if errorlevel 1 exit /b 1
echo [MTS] Universe src=%MTS_UNIVERSE_SRC% pass_s=%MTS_PASS_SYMBOLS%

if "%MTS_PASS_SYMBOLS%"=="1" (
  "%PY%" stock_analysis\rocket_tbn.py data\newdata\data -o drive -w 22 --aggressive --no-regression --mts-sheet-parity -v band_pct=0.018 -v touch_threshold=2 -v strong_post_pivot_bars=7 -v strong_post_pivot_pct=0.06 -v strong_pre_pivot_bars=7 -v strong_pre_pivot_pct=0.12 -v target_pct=1.22 -v stop_pct=0.934 -v stop_pct_is_multiplier=true -v stop_loss_based=trigger_low --symbol-reentry-cooldown-days 20 -v min_upper_wick_atr_at_trigger=0.25 -v min_dist_to_52w_high_pct_at_trigger=25 -s "!MTS_SYMBOLS!" !MTS_FORWARD!
) else (
  "%PY%" stock_analysis\rocket_tbn.py data\newdata\data -o drive -w 22 --aggressive --no-regression --mts-sheet-parity -v band_pct=0.018 -v touch_threshold=2 -v strong_post_pivot_bars=7 -v strong_post_pivot_pct=0.06 -v strong_pre_pivot_bars=7 -v strong_pre_pivot_pct=0.12 -v target_pct=1.22 -v stop_pct=0.934 -v stop_pct_is_multiplier=true -v stop_loss_based=trigger_low --symbol-reentry-cooldown-days 20 -v min_upper_wick_atr_at_trigger=0.25 -v min_dist_to_52w_high_pct_at_trigger=25 !MTS_FORWARD!
)
if errorlevel 1 exit /b 1
call "%~dp0run_copy_latest.bat"
exit /b %errorlevel%
