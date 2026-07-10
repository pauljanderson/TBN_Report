@echo off
rem BRT zone backtest (whitelist) — outputs BRT_Closed|Open|Scanner|Watchlist_<ts>.csv in drive\
rem Override symbols: set BRT_SYMBOLS=SYM1,SYM2 before calling
setlocal EnableExtensions
cd /d "%~dp0"
call "%~dp0daily_run_env.bat"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1
set "PS_ARGS="
if exist "%~dp0%PER_SYMBOL_SETTINGS%" set "PS_ARGS=--per-symbol-settings %PER_SYMBOL_SETTINGS%"
"%PY%" stock_analysis\rocket_brt.py data\newdata\data -o drive -w 5 --no-regression --print-zones -v stop_pct=0.934 -v target_pct=1.21 -v too_high_multiplier=0 -v band_pct=0.0154 -v strong_pre_pivot_pct=0.081 -v strong_post_pivot_pct=0.108 -v strong_pre_pivot_bars=7 -v strong_post_pivot_bars=7 -v breakout_bars=100 -v tight_range_threshold_pct=0.35 -v tight_range_lookback=105 -v sheet_breakout_scan_start_row_delta=2 -v sheet_touch_pullback_bars=10 -v brt_sheet_touch=true -v max_positions=16 -v min_spy_compare_1y_at_trigger=-1000 -v sheet_red_to_green_entry_enabled=true -v sheet_dw_countif_include_prior_bar_date=false -v growth_filter_enabled=true -v min_ind_score=-1 -v compute_beta=false -v brt_zones=true -v yh_zones=false %PS_ARGS% -s "%BRT_SYMBOLS%"
exit /b %errorlevel%
