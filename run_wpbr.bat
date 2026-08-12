@echo off
rem WPBR (Pivot Break and Retest) — weekly pivot zones, weekly BO, daily retest entry.
rem Standalone: double-click or call from DailyRun.
rem Universe: drive\universes\WPBR_universe.csv (one ticker per line) — Mag9 production
rem Override: run_wpbr.bat path\to\test_universe.csv
rem          set WPBR_UNIVERSE_CSV=...
rem          set WPBR_SYMBOLS=AAPL,MSFT
rem Full universe (all data\newdata\data\*.csv) — no env vars:
rem   run_wpbr.bat ALL
rem   run_wpbr.bat --all
rem   run_wpbr.bat "*"          (quote * in PowerShell; bare * often expands)
rem Legacy env: set WPBR_SYMBOLS=* / ALL / set WPBR_ALL_CSV=1
rem IND_TC_* on Closed: add -v use_indicators=true (report-only; keep indicator_buy=off for no gates).
rem Extra CLI: trailing %* forwarded to rocket_tbn (leading .csv / ALL stripped; -v kept).
rem   run_wpbr.bat -v wpbr_merge_overlapping_zones=true
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

call "%~dp0tools\apply_universe_cli_arg.bat" WPBR_UNIV_ARG %1 %2
call "%~dp0tools\build_cli_forward.bat" WPBR_FORWARD "%WPBR_UNIV_ARG%" %*
call "%~dp0tools\load_universe_csv.bat" WPBR "%WPBR_UNIV_ARG%"
if errorlevel 1 exit /b 1
echo [WPBR] Universe src=%WPBR_UNIVERSE_SRC% pass_s=%WPBR_PASS_SYMBOLS%

rem Production Mag9 (no start_date): target 1.22, stop 0.91, SC after win, nosamebarexit
rem (WPBR forces sheet_no_entry_same_bar_after_exit=false). Earlier pre-2016 trades are intentional
rem in the current golden — do NOT add -v start_date=2016 for DailyRun / reconcile freeze.
rem HALF_UP retest compares + variant C pivot rounding are in-engine (wpbr_zones.py).
rem Optional (OFF by default): -v wpbr_merge_overlapping_zones=true
rem   merges overlapping WPBR bands; Closed/Open ZONE_STRENGTH = member count (1=unmerged).
rem max_market_cap=0 / min_market_cap=0: disable post-enrich cap filter (same AMD-wipe class of bug).
if "%WPBR_PASS_SYMBOLS%"=="1" (
  "%PY%" stock_analysis\rocket_tbn.py data\newdata\data -o drive -w 30 --aggressive --use-duckdb --no-regression --print-zones -v wpbr_zones=true -v brt_zones=false -v yh_zones=false -v vec_zones=false -v band_pct=0.015 -v strong_pre_pivot_bars=3 -v strong_pre_pivot_pct=0.10 -v strong_post_pivot_bars=3 -v strong_post_pivot_pct=0.10 -v strong_pivot_mode=either -v wpbr_breakout_confirmation=0.03 -v wpbr_max_days_after_retest=2 -v wpbr_second_chance_after_win=true -v growth_filter_enabled=false -v min_spy_compare_1y_at_trigger=-1000 -v ind_score_weights_path="" -v too_high_multiplier=0 -v target_pct=1.22 -v stop_pct=0.91 -v sheet_no_entry_same_bar_after_exit=false -v use_indicators=true -v max_market_cap=0 -v min_market_cap=0 -s "!WPBR_SYMBOLS!" !WPBR_FORWARD!
) else (
  "%PY%" stock_analysis\rocket_tbn.py data\newdata\data -o drive -w 30 --aggressive --use-duckdb --no-regression --print-zones -v wpbr_zones=true -v brt_zones=false -v yh_zones=false -v vec_zones=false -v band_pct=0.015 -v strong_pre_pivot_bars=3 -v strong_pre_pivot_pct=0.10 -v strong_post_pivot_bars=3 -v strong_post_pivot_pct=0.10 -v strong_pivot_mode=either -v wpbr_breakout_confirmation=0.03 -v wpbr_max_days_after_retest=2 -v wpbr_second_chance_after_win=true -v growth_filter_enabled=false -v min_spy_compare_1y_at_trigger=-1000 -v ind_score_weights_path="" -v too_high_multiplier=0 -v target_pct=1.22 -v stop_pct=0.91 -v sheet_no_entry_same_bar_after_exit=false -v use_indicators=true -v max_market_cap=0 -v min_market_cap=0 !WPBR_FORWARD!
)
exit /b %errorlevel%
