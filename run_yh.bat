@echo off
rem Year-High (YH) backtest — outputs YH_Closed|Open|Scanner|Watchlist_<ts>.csv in drive\
setlocal EnableExtensions
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1
"%PY%" stock_analysis\rocket_brt.py data\newdata\data -o drive -w 5 --aggressive --use-duckdb --no-regression -v yh_zones=true -v brt_zones=false -v band_pct=0.0099 -v strong_pre_pivot_pct=0.12 -v strong_post_pivot_pct=0.109 -v min_spy_compare_1y_at_trigger=-1000 -v ind_score_weights_path="" -v too_high_multiplier=0 -v yh_move_away_pct=0.031 -v target_pct=1.27 -v stop_pct=0.923 -s "NVDA, MSFT, AAPL, AMZN, META, NFLX, AMD, AU, GOOGL,TSLA"
exit /b %errorlevel%
