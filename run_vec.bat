@echo off
rem VEC (Volume + prior-period Extreme Confluence) — outputs VEC_* CSVs in drive\
rem Standalone: double-click or call from DailyRun. Override: set VEC_SYMBOLS=SYM1,SYM2 before calling.
setlocal EnableExtensions
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

if not defined VEC_SYMBOLS set "VEC_SYMBOLS=NVDA,MSFT,AAPL,AMZN,META,GOOGL,TSLA,AMD,NFLX"

"%PY%" stock_analysis\rocket_brt.py data\newdata\data -o drive -w 5 --aggressive --use-duckdb --no-regression --print-zones -v vec_zones=true -v brt_zones=false -v yh_zones=false -v band_pct=0.012 -v vec_vp_lookback=60 -v vec_prior_bars=5 -v vec_confluence_pct=0.0075 -v vec_move_away_pct=0.02 -v min_spy_compare_1y_at_trigger=-1000 -v ind_score_weights_path="" -v too_high_multiplier=0 -v target_pct=1.24 -v stop_pct=0.927 -s "%VEC_SYMBOLS%"
exit /b %errorlevel%
