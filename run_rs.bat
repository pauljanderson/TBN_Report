@echo off
rem RS (Relative Strength) — SPY_COMPARE 1Y/2Y/3Y > 0 AND IND_TC_*_OUTLOOK all Strong on trigger
rem bar T close → buy next open (T+1). Never re-check TC/SPY_COMPARE on the entry bar.
rem Engine: rocket_tbn.py (relative_strength / rs_mode) — same Closed/Open/Scanner/Watchlist/Report
rem writers as YH/MTS/BRT. Outputs RS_*_<ts>.csv in drive\
rem Standalone: double-click or call from DailyRun.
rem Override before calling:
rem   set RS_SYMBOLS=AAPL,MSFT
rem   set RS_TARGET=1.25
rem   set RS_STOP=0.88
rem
rem Inherits (via rocket_tbn -v): target_pct, stop_pct, use_indicators, start_date/entry_start_date,
rem   max_positions, duckdb, workers, stop_pct_is_multiplier, symbol_reentry_cooldown_days, etc.
rem Unused in RS mode: band_pct, yh_*/wpbr_*/brt zone pivots, touch_threshold, retest flags.
rem TC Strong gate: rs_require_tc_strong=true (default) on trigger bar; keep use_indicators=true.
rem
rem Optional O'Neil-style RS filters (all evaluated on trigger bar T only; default off here):
rem   -v rs_max_pct_below_52w_high=X   Close_T >= 52w_high_T*(1-X); X=0.15 ≈ within 15%% of high;
rem                                   <=0 disables. Alias in %%-pts: max_dist_to_52w_high_pct_at_trigger.
rem   -v growth_filter_enabled=true -v growth_bars=N
rem                                   Close_T >= Close_{T-N}; N e.g. 252/504/756. Off below for production.
rem   -v rs_spy_int_tc_not_weak=true  SPY IND_TC_INT_OUTLOOK on T not Weak (Strong|Neutral ok).
rem Optional RS sell_breakdown (default off = normal target/stop only):
rem   -v sell_breakdown=breakdown_plus   normal exits OR breakdown (SPY_COMPARE any ^<0 OR TC not Strong)
rem   -v sell_breakdown=breakdown_only   breakdown exits only, SPY OR TC (no stop/target schedule)
rem   -v sell_breakdown=breakdown_both   breakdown exits only when SPY AND TC both broken same bar

rem Sweep/results: drive\paul_experiments\rs_oneil_filters\
setlocal EnableExtensions
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

if not defined RS_TARGET set "RS_TARGET=1.25"
if not defined RS_STOP set "RS_STOP=0.88"

rem Curated 55 from drive\paul_experiments\spy_tc_strong_system\universe_then_curated\CURATED_SYMBOLS.txt
rem if not defined RS_SYMBOLS set "RS_SYMBOLS=TRV,WELL,CTAS,CASY,AFL,BDX,CW,CB,BSX,CPRT,AJG,HWM,NVDA,TJX,FISV,PRI,MCD,ATEYY,MCK,POOL,FICO,V,QQQ,ENSG,DHR,UNH,DECK,RELX,RBC,ORLY,MSCI,ROP,CAH,ADBE,BRO,MCO,COST,NFLX,BBIO,POWL,BR,LOGI,TMO,FIX,AER,CHTR,PGR,LII,EME,TDY,ETR,AXSM,SYK,AVGO,WST"
if not defined RS_SYMBOLS set "RS_SYMBOLS=AAPL,NVDA,GOOGL,MSFT,AMZN,TSM,AVGO,META,LLY,JPM,WMT,MU,AMD,V,XOM,ASML,MA"

rem Neutralize BRT zone defaults that are NOT RS rules (RS already requires SPY_COMPARE > 0):
rem   min_spy_compare_1y_at_trigger=50 would wrongly cut ~1001 curated trades down to ~369.
rem   too_high_multiplier=1.058 is a BRT gap gate; experiment/RS baseline has it off.
"%PY%" stock_analysis\rocket_tbn.py data\newdata\data -o drive -w 25 --no-regression --aggressive --relative-strength -v rs_mode=true -v brt_zones=false -v yh_zones=false -v wpbr_zones=false -v rl_mode=false -v target_pct=%RS_TARGET% -v stop_pct=%RS_STOP% -v stop_pct_is_multiplier=true -v use_indicators=true -v indicator_buy=off -v rs_require_tc_strong=true -v growth_filter_enabled=false -v min_spy_compare_1y_at_trigger=0 -v atr_days=0 -v too_high_multiplier=0 -v rs_max_pct_below_52w_high=0 -v rs_spy_int_tc_not_weak=false -s "%RS_SYMBOLS%"
exit /b %errorlevel%
