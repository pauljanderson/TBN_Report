@echo off
rem WPBR (Pivot Break and Retest) — weekly pivot zones, weekly BO, daily retest entry.
rem Standalone: double-click or call from DailyRun.
rem Universe: full data\newdata\data\*.csv (DailyRun default since 2026-10-01 freeze).
rem Override: run_wpbr.bat path\to\test_universe.csv
rem          set WPBR_UNIVERSE_CSV=...
rem          set WPBR_SYMBOLS=AAPL,MSFT
rem          run_wpbr.bat drive\universes\WPBR_universe.csv   (the old 9-name Mag9 list)
rem Full universe is also: run_wpbr.bat ALL / --all / "*" (quote * in PowerShell).
rem Legacy env: set WPBR_SYMBOLS=* / ALL / set WPBR_ALL_CSV=1
rem Indicators OFF by default (2026-10-02): use_indicators=false. Report IND_* columns
rem are not precomputed on the DailyRun path (was ~18%% of bt time with indicator_buy=off).
rem Opt-in report columns: -v use_indicators=true (keep indicator_buy=off for no gates).
rem Incremental resume (DEFAULT OFF until parity): set WPBR_INCREMENTAL=1 or
rem   -v wpbr_incremental=true
rem Warm start picks up from last bar when freeze knobs+code+universe fingerprint match;
rem mismatch / WPBR_INCREMENTAL_FORCE_FULL=1 → full rebuild. State: drive\WPBR_incr_state\
rem Extra CLI: trailing %* forwarded to rocket_tbn (leading .csv / ALL stripped; -v kept).
rem   run_wpbr.bat -v wpbr_merge_overlapping_zones=true
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

call "%~dp0tools\apply_universe_cli_arg.bat" WPBR_UNIV_ARG %1 %2
rem No CSV argument and no WPBR_SYMBOLS override → full data directory.
if not defined WPBR_SYMBOLS (
  if not defined WPBR_UNIV_ARG set "WPBR_UNIV_ARG=ALL"
  if "%WPBR_UNIV_ARG%"=="" set "WPBR_UNIV_ARG=ALL"
)
call "%~dp0tools\build_cli_forward.bat" WPBR_FORWARD "%WPBR_UNIV_ARG%" %*
call "%~dp0tools\load_universe_csv.bat" WPBR "%WPBR_UNIV_ARG%"
if errorlevel 1 exit /b 1
echo [WPBR] Universe src=%WPBR_UNIVERSE_SRC% pass_s=%WPBR_PASS_SYMBOLS%

rem DailyRun -w sets DAILYRUN_WORKERS. Standalone default stays 30. Explicit WPBR_WORKERS wins.
if not defined WPBR_WORKERS if defined DAILYRUN_WORKERS set "WPBR_WORKERS=%DAILYRUN_WORKERS%"
if not defined WPBR_WORKERS set "WPBR_WORKERS=30"

rem Production freeze 2026-10-02 (22%% overhead arm of
rem wpbr_overhead20_vs22_t20s8_ab_20261002, engine stamp 261002051403).
rem Full warehouse. No start_date. Second chance after win.
rem nosamebarexit (sheet_no_entry_same_bar_after_exit=false).
rem Overhead: wpbr_overhead_band_pct=0.22. Skip a buy when an earlier WPBR zone
rem has its bottom above this zone's top and that gap is 22%% or less.
rem Target 1.20 (full sale at 20%% above the buy).
rem Stop 0.92: 0.92 times the trigger-day low (8%% under the low of the day
rem before the buy). Not 8%% under the entry price.
rem growth_filter_enabled stays false. min_history_bars=0 (this arm does not
rem require 756 sessions of history; the close-must-be-higher rule stays off).
rem Do NOT add -v start_date=2016. Pre-2016 fills stay in the golden.
rem HALF_UP retest compares + variant C pivot rounding are in-engine (wpbr_zones.py).
rem Optional (OFF by default): -v wpbr_merge_overlapping_zones=true
rem   merges overlapping WPBR bands; Closed/Open ZONE_STRENGTH = member count (1=unmerged).
rem max_market_cap=0 / min_market_cap=0: disable post-enrich cap filter (same AMD-wipe class of bug).
if "%WPBR_PASS_SYMBOLS%"=="1" (
  "%PY%" stock_analysis\rocket_tbn.py data\newdata\data -o drive -w !WPBR_WORKERS! --aggressive --use-duckdb --no-regression --print-zones -v wpbr_zones=true -v brt_zones=false -v yh_zones=false -v vec_zones=false -v band_pct=0.015 -v strong_pre_pivot_bars=3 -v strong_pre_pivot_pct=0.10 -v strong_post_pivot_bars=3 -v strong_post_pivot_pct=0.10 -v strong_pivot_mode=either -v wpbr_breakout_confirmation=0.03 -v wpbr_max_days_after_retest=2 -v wpbr_second_chance_after_win=true -v growth_filter_enabled=false -v growth_bars=756 -v growth_history_slack_bars=0 -v min_history_bars=0 -v growth_filter_strict_gt=false -v growth_min_pct=0 -v wpbr_overhead_band_pct=0.22 -v min_spy_compare_1y_at_trigger=-1000 -v ind_score_weights_path="" -v too_high_multiplier=0 -v target_pct=1.20 -v stop_pct=0.92 -v sheet_no_entry_same_bar_after_exit=false -v use_indicators=false -v max_market_cap=0 -v min_market_cap=0 -s "!WPBR_SYMBOLS!" !WPBR_FORWARD!
) else (
  "%PY%" stock_analysis\rocket_tbn.py data\newdata\data -o drive -w !WPBR_WORKERS! --aggressive --use-duckdb --no-regression --print-zones -v wpbr_zones=true -v brt_zones=false -v yh_zones=false -v vec_zones=false -v band_pct=0.015 -v strong_pre_pivot_bars=3 -v strong_pre_pivot_pct=0.10 -v strong_post_pivot_bars=3 -v strong_post_pivot_pct=0.10 -v strong_pivot_mode=either -v wpbr_breakout_confirmation=0.03 -v wpbr_max_days_after_retest=2 -v wpbr_second_chance_after_win=true -v growth_filter_enabled=false -v growth_bars=756 -v growth_history_slack_bars=0 -v min_history_bars=0 -v growth_filter_strict_gt=false -v growth_min_pct=0 -v wpbr_overhead_band_pct=0.22 -v min_spy_compare_1y_at_trigger=-1000 -v ind_score_weights_path="" -v too_high_multiplier=0 -v target_pct=1.20 -v stop_pct=0.92 -v sheet_no_entry_same_bar_after_exit=false -v use_indicators=false -v max_market_cap=0 -v min_market_cap=0 !WPBR_FORWARD!
)
exit /b %errorlevel%
