@echo off
rem RS (Relative Strength) — SPY_COMPARE 1Y/2Y/3Y > 0 AND IND_TC_*_OUTLOOK all Strong on trigger
rem bar T close → buy next open (T+1). Never re-check TC/SPY_COMPARE on the entry bar.
rem Engine: rocket_tbn.py (relative_strength / rs_mode) — same Closed/Open/Scanner/Watchlist/Report
rem writers as YH/MTS/BRT. Outputs RS_*_<ts>.csv in drive\
rem Standalone: double-click or call from DailyRun.
rem Universe: drive\universes\RS_universe.csv (one ticker per line)
rem Override: run_rs.bat path\to\test_universe.csv
rem          set RS_UNIVERSE_CSV=...
rem          set RS_SYMBOLS=AAPL,MSFT
rem Full universe (all data\newdata\data\*.csv) — no env vars:
rem   run_rs.bat ALL
rem   run_rs.bat --all
rem   run_rs.bat "*"          (quote * in PowerShell; bare * often expands)
rem Legacy env still works: set RS_SYMBOLS=* / ALL / set RS_ALL_CSV=1
rem          set RS_TARGET=1.25
rem          set RS_STOP=0.85
rem          set RS_TIME_STOP=252   (default; set 0 to disable TIME exit)
rem
rem Production / reconcile freeze (see drive\paul_experiments\rs_baseline_*\README.md):
rem   rs_spy_int_tc_not_weak=true, symbol_reentry_cooldown_days=60
rem   target_pct=1.25, stop_pct=0.85 (Closed STOP/TARGET ratios; RS_STOP default)
rem   time_stop_days=252 (default; override set RS_TIME_STOP=0 for experiments / off)
rem   Freeze stamp 260807141317: expanded 65-name FIT universe + stop 0.85
rem   Prior freeze 260807114545: FIT-54, stop 0.88 / target 1.25 / time_stop=252
rem   Prior freeze 260801111512 had time_stop_days=0 (no TIME exit)
rem   Adopted earlier: rs_noft_time_ab arm 15_time_252; post252 A/B stop widen 0.85
rem   Prior research stamp 260801104344 used 0.934/1.21 — NOT production
rem   NOT adopted: fat_stops arm 03_stop_091 (stop 0.91)
rem   Universe: drive\universes\RS_universe.csv (65 names; synced from RS_universe_expand.csv)
rem
rem Inherits (via rocket_tbn -v): target_pct, stop_pct, use_indicators, start_date/entry_start_date,
rem   max_positions, duckdb, workers, stop_pct_is_multiplier, symbol_reentry_cooldown_days,
rem   time_stop_days, etc.
rem Unused in RS mode: band_pct, yh_*/wpbr_*/brt zone pivots, touch_threshold, retest flags.
rem TC Strong gate: rs_require_tc_strong=true (default) on trigger bar; keep use_indicators=true.
rem
rem Optional O'Neil-style RS filters (all evaluated on trigger bar T only; default off here):
rem   -v rs_max_pct_below_52w_high=X   Close_T >= 52w_high_T*(1-X); X=0.15 ≈ within 15%% of high;
rem                                   <=0 disables. Alias in %%-pts: max_dist_to_52w_high_pct_at_trigger.
rem   -v growth_filter_enabled=true -v growth_bars=N
rem                                   Close_T >= Close_{T-N}; N e.g. 252/504/756. Off below for production.
rem   -v rs_spy_int_tc_not_weak=true  SPY IND_TC_INT_OUTLOOK on T not Weak (Strong|Neutral ok).
rem Optional post-TARGET-only re-entry (same fields as RL; default off in production):
rem   -v rl_post_target_reentry_bars=N -v rl_post_target_reentry_mode=none|under_sma_limit|min_stack|stop_loss
rem Optional RS sell_breakdown (default off = normal target/stop only):
rem   -v sell_breakdown=breakdown_plus   normal exits OR breakdown (SPY_COMPARE any ^<0 OR TC not Strong)
rem   -v sell_breakdown=breakdown_only   breakdown exits only, SPY OR TC (no stop/target schedule)
rem   -v sell_breakdown=breakdown_both   breakdown exits only when SPY AND TC both broken same bar

rem Sweep/results: drive\paul_experiments\rs_oneil_filters\
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

if not defined RS_TARGET set "RS_TARGET=1.25"
if not defined RS_STOP set "RS_STOP=0.85"
if not defined RS_TIME_STOP set "RS_TIME_STOP=252"

call "%~dp0tools\apply_universe_cli_arg.bat" RS_UNIV_ARG %1 %2
call "%~dp0tools\load_universe_csv.bat" RS "%RS_UNIV_ARG%"
if errorlevel 1 exit /b 1
echo [RS] Universe src=%RS_UNIVERSE_SRC% pass_s=%RS_PASS_SYMBOLS% time_stop_days=%RS_TIME_STOP%

rem Neutralize BRT zone defaults that are NOT RS rules (RS already requires SPY_COMPARE > 0):
rem   min_spy_compare_1y_at_trigger=50 would wrongly cut ~1001 curated trades down to ~369.
rem   too_high_multiplier=1.058 is a BRT gap gate; experiment/RS baseline has it off.
if "%RS_PASS_SYMBOLS%"=="1" (
  "%PY%" stock_analysis\rocket_tbn.py data\newdata\data -o drive -w 12 --no-regression --aggressive --relative-strength -v rs_mode=true -v brt_zones=false -v yh_zones=false -v wpbr_zones=false -v rl_mode=false -v target_pct=%RS_TARGET% -v stop_pct=%RS_STOP% -v stop_pct_is_multiplier=true -v use_indicators=true -v indicator_buy=off -v rs_require_tc_strong=true -v growth_filter_enabled=false -v min_spy_compare_1y_at_trigger=0 -v atr_days=0 -v too_high_multiplier=0 -v rs_max_pct_below_52w_high=0 -v rs_spy_int_tc_not_weak=true -v symbol_reentry_cooldown_days=60 -v time_stop_days=%RS_TIME_STOP% -s "!RS_SYMBOLS!"
) else (
  "%PY%" stock_analysis\rocket_tbn.py data\newdata\data -o drive -w 12 --no-regression --aggressive --relative-strength -v rs_mode=true -v brt_zones=false -v yh_zones=false -v wpbr_zones=false -v rl_mode=false -v target_pct=%RS_TARGET% -v stop_pct=%RS_STOP% -v stop_pct_is_multiplier=true -v use_indicators=true -v indicator_buy=off -v rs_require_tc_strong=true -v growth_filter_enabled=false -v min_spy_compare_1y_at_trigger=0 -v atr_days=0 -v too_high_multiplier=0 -v rs_max_pct_below_52w_high=0 -v rs_spy_int_tc_not_weak=true -v symbol_reentry_cooldown_days=60 -v time_stop_days=%RS_TIME_STOP%
)
exit /b %errorlevel%
