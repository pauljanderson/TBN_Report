@echo off
rem IND indicator-only backtest (full DuckDB universe) — outputs IND_Closed|Open|... in drive\
rem Standalone: double-click or call from DailyRun.
rem Universe: drive\universes\IND_universe.csv (default * = full scan / omit -s)
rem Override: run_ind.bat path\to\test_universe.csv
rem          set IND_UNIVERSE_CSV=...
rem          set IND_SYMBOLS=AAPL,MSFT
rem Full universe (all data\newdata\data\*.csv) — no env vars:
rem   run_ind.bat ALL
rem   run_ind.bat --all
rem   run_ind.bat "*"          (quote * in PowerShell; bare * often expands)
rem Legacy env: set IND_SYMBOLS=* / ALL / set IND_ALL_CSV=1
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

call "%~dp0tools\apply_universe_cli_arg.bat" IND_UNIV_ARG %1 %2
call "%~dp0tools\load_universe_csv.bat" IND "%IND_UNIV_ARG%"
if errorlevel 1 exit /b 1
echo [IND] Universe src=%IND_UNIVERSE_SRC% pass_s=%IND_PASS_SYMBOLS%

if "%IND_PASS_SYMBOLS%"=="1" (
  "%PY%" stock_analysis\rocket_tbn.py data\newdata\data -o drive -w 30 --aggressive --use-duckdb --no-regression -v target_pct=1.24 -v trailing_stop_increment=0 -v strong_pre_pivot_pct=0.081 -v strong_post_pivot_pct=0.109 -v atr_progress=0 -v atr_days=0 -v compute_beta=true -v min_avg_volume_10d_at_entry=0 -v min_atr_pct_at_trigger=8.1 -v max_atr_pct_at_trigger=0 -v use_indicators=true -v indicator_buy=only -v indicator_diff=7 -v indicator_sides=long -v transaction_type=long -v atr_target=2.2 -v atr_stop=1.4 -v max_ind_entry_neutral_n=30 -v min_ind_score=-2 -v yh_zones=false -v aggressive_avg_positions=20 -s "!IND_SYMBOLS!"
) else (
  "%PY%" stock_analysis\rocket_tbn.py data\newdata\data -o drive -w 30 --aggressive --use-duckdb --no-regression -v target_pct=1.24 -v trailing_stop_increment=0 -v strong_pre_pivot_pct=0.081 -v strong_post_pivot_pct=0.109 -v atr_progress=0 -v atr_days=0 -v compute_beta=true -v min_avg_volume_10d_at_entry=0 -v min_atr_pct_at_trigger=8.1 -v max_atr_pct_at_trigger=0 -v use_indicators=true -v indicator_buy=only -v indicator_diff=7 -v indicator_sides=long -v transaction_type=long -v atr_target=2.2 -v atr_stop=1.4 -v max_ind_entry_neutral_n=30 -v min_ind_score=-2 -v yh_zones=false -v aggressive_avg_positions=20
)
exit /b %errorlevel%
