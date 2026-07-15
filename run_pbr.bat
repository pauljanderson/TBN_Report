@echo off
rem PBR (Pivot Break and Retest) — weekly pivot zones, weekly BO, daily retest entry.
setlocal EnableExtensions
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1
"%PY%" stock_analysis\rocket_brt.py data\newdata\data -o drive -w 5 --aggressive --use-duckdb --no-regression --print-zones -v pbr_zones=true -v brt_zones=false -v yh_zones=false -v vec_zones=false -v band_pct=0.015 -v strong_pre_pivot_bars=3 -v strong_pre_pivot_pct=0.10 -v strong_post_pivot_bars=3 -v strong_post_pivot_pct=0.10 -v strong_pivot_mode=either -v pbr_breakout_confirmation=0.03 -v pbr_max_days_after_retest=2 -v growth_filter_enabled=false -v min_spy_compare_1y_at_trigger=-1000 -v ind_score_weights_path="" -v too_high_multiplier=0 -v target_pct=1.24 -v stop_pct=0.927 -s "AMZN,AMD,AU,GOOGL,META,TSLA"
exit /b %errorlevel%
