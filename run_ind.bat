@echo off
rem IND indicator-only backtest (full DuckDB universe) — outputs IND_Closed|Open|... in drive\
rem Standalone: double-click or call from DailyRun. No -s filter (full universe by design).
setlocal EnableExtensions
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1
"%PY%" stock_analysis\rocket_brt.py data\newdata\data -o drive -w 30 --aggressive --use-duckdb --no-regression -v target_pct=1.24 -v trailing_stop_increment=0 -v strong_pre_pivot_pct=0.081 -v strong_post_pivot_pct=0.109 -v atr_progress=0 -v atr_days=0 -v compute_beta=true -v min_avg_volume_10d_at_entry=0 -v min_atr_pct_at_trigger=8.1 -v max_atr_pct_at_trigger=0 -v use_indicators=true -v indicator_buy=only -v indicator_diff=7 -v indicator_sides=long -v transaction_type=long -v atr_target=2.2 -v atr_stop=1.4 -v max_ind_entry_neutral_n=30 -v min_ind_score=-2 -v yh_zones=false -v aggressive_avg_positions=20
exit /b %errorlevel%
