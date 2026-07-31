@echo off
rem Year-High (YH) backtest — outputs YH_Closed|Open|Scanner|Watchlist_<ts>.csv in drive\
rem Standalone: double-click or call from DailyRun. Override: set YH_SYMBOLS=SYM1,SYM2 before calling.
rem IND_TC_* on Closed: change use_indicators=false → true below (report-only; indicator_buy=off = no gates).
rem stop_compare_round_decimals=-1: full-float stop vs Low/High (no 2-dec round). Fixes false STOP
rem e.g. AU 2025-02-28 stop 28.44964 vs Low 28.45 (sheet keeps 28.4496; Low does not breach).
rem YH-only via this bat; shared rocket_tbn default remains 2 for BRT/WPBR/RL/RS.
setlocal EnableExtensions
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

if not defined YH_SYMBOLS set "YH_SYMBOLS=AAPL,AMD,AMZN,AU,GOOGL,META,MSFT,NFLX,NVDA,TSLA"

"%PY%" stock_analysis\rocket_tbn.py data\newdata\data -o drive -w 32 --aggressive --use-duckdb --no-regression -v yh_zones=true -v brt_zones=false -v wpbr_zones=false -v rl_mode=false -v band_pct=0.015 -v yh_move_away_pct=0.03 -v yh_lookback=252 -v yh_memory_mode=sheet -v strong_pre_pivot_bars=7 -v strong_pre_pivot_pct=0.12 -v strong_post_pivot_bars=7 -v strong_post_pivot_pct=0.109 -v strong_pivot_mode=off -v target_pct=1.21 -v stop_pct=0.934 -v stop_pct_is_multiplier=true -v stop_compare_round_decimals=-1 -v too_high_multiplier=0 -v max_spy_compare_1y_at_trigger=0 -v min_spy_compare_1y_at_trigger=0 -v min_atr_pct_at_trigger=0 -v max_atr_pct_at_trigger=0 -v growth_filter_enabled=true -v growth_bars=756 -v use_indicators=false -v indicator_buy=off -v ind_score_weights_path="" -v min_ind_score=0  -s "%YH_SYMBOLS%"
exit /b %errorlevel%

