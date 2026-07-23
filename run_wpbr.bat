@echo off
rem WPBR (Pivot Break and Retest) — weekly pivot zones, weekly BO, daily retest entry.
rem Standalone: double-click or call from DailyRun. Override: set WPBR_SYMBOLS=SYM1,SYM2 before calling.
rem IND_TC_* on Closed: add -v use_indicators=true (report-only; keep indicator_buy=off for no gates).
setlocal EnableExtensions
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

rem if not defined WPBR_SYMBOLS set "WPBR_SYMBOLS=META,CSX,HTHIY,MPC,ISNPY,MSFT,SYK,MCO,MITSY,MRK,WFC,AMD,PGR,VRTX,AVGO,PANW,BKNG,MCK,BLK,ING,ITW,XOM,BN,ATEYY,SCHW,KLAC,ADP,TJX,IBKR,CME,WMB,TSLA,ACN,OVCHY,NEM,PLD,RY,STX,TSM,SONY,TMUS,MDLZ,RTX,AMT,ASML,SCCO,DBSDY,JCI,SIEGY,LLY,CTAS,MU,NEE,TOELY,ABBV,V,MNST,PFE,WMT,GS,HCA,LRCX,ZURVY,MA,AMZN,TXN,MAR,UNP,WELL,UNH,EADSY,CVX,GD,SHW,SO,MO,T,C,SBGSY,ADBE,CM"

if not defined WPBR_SYMBOLS set "WPBR_SYMBOLS=AAPL,AMD,AMZN,AU,META,MSFT,NVDA,NFLX,GOOGL,TSLA"


rem Parity baseline (MarkTen sheet reconcile): target 1.22, stop 0.91, start_date 2016 (pivot floor),
rem SC after win, nosamebarexit (WPBR forces sheet_no_entry_same_bar_after_exit=false). HALF_UP retest
rem compares + variant C pivot rounding are in-engine (wpbr_zones.py); classic BRT path unchanged.
rem Optional (OFF by default for sheet parity): -v wpbr_merge_overlapping_zones=true
rem   merges overlapping WPBR bands; Closed/Open ZONE_STRENGTH = member count (1=unmerged).
"%PY%" stock_analysis\rocket_brt.py data\newdata\data -o drive -w 10 --aggressive --use-duckdb --no-regression --print-zones -v wpbr_zones=true -v brt_zones=false -v yh_zones=false -v vec_zones=false -v band_pct=0.015 -v strong_pre_pivot_bars=3 -v strong_pre_pivot_pct=0.10 -v strong_post_pivot_bars=3 -v strong_post_pivot_pct=0.10 -v strong_pivot_mode=either -v wpbr_breakout_confirmation=0.03 -v wpbr_max_days_after_retest=2 -v wpbr_second_chance_after_win=true -v growth_filter_enabled=false -v min_spy_compare_1y_at_trigger=-1000 -v ind_score_weights_path="" -v too_high_multiplier=0 -v target_pct=1.22 -v stop_pct=0.91 -v sheet_no_entry_same_bar_after_exit=false -v use_indicators=true -s "%WPBR_SYMBOLS%"
exit /b %errorlevel%

