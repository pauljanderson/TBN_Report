@echo off
rem IND indicator-only backtest (full DuckDB universe) — outputs IND_Closed|Open|... in drive\
setlocal EnableExtensions
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1
"%PY%" stock_analysis\rocket_brt.py data\newdata\data -o drive -w 6 --aggressive --use-duckdb --no-regression -v target_pct=1.21 -v trailing_stop_increment=0 -v strong_pre_pivot_pct=0.081 -v strong_post_pivot_pct=0.109 -v atr_progress=0 -v atr_days=0 -v compute_beta=true -v min_avg_volume_10d_at_entry=0 -v min_atr_pct_at_trigger=8.1 -v max_atr_pct_at_trigger=0 -v use_indicators=true -v indicator_buy=only -v indicator_diff=8 -v indicator_sides=long -v transaction_type=long -v atr_target=2.0 -v atr_stop=1.2 -v max_ind_entry_neutral_n=40 -v min_ind_score=0 -v yh_zones=false -v aggressive_avg_positions=25
exit /b %errorlevel%
