@echo off
rem BRT zone backtest (whitelist) — outputs BRT_Closed|Open|Scanner|Watchlist_<ts>.csv in drive\
rem Standalone: double-click or call from DailyRun.
rem Universe: drive\universes\BRT_universe.csv (one ticker per line)
rem Override: run_brt.bat path\to\test_universe.csv
rem          set BRT_UNIVERSE_CSV=...
rem          set BRT_SYMBOLS=AAPL,MSFT
rem Full universe (all data\newdata\data\*.csv) — no env vars:
rem   run_brt.bat ALL
rem   run_brt.bat --all
rem   run_brt.bat "*"          (quote * in PowerShell; bare * often expands)
rem Legacy env: set BRT_SYMBOLS=* / ALL / set BRT_ALL_CSV=1
rem IND_TC_* on Closed: add -v use_indicators=true (report-only; keep indicator_buy=off for no gates).
rem Optional research flag (leave OFF in production): add `-v brt_like_wpbr=true` to switch the
rem   breakout/retest/entry path to the WPBR-like daily package (Stage1/2 break+confirm, hold-above
rem   retest from confirm+1, green entry window; drops red-to-green/growth/COUNTIF). Everything else
rem   (zones, stops, targets, portfolio) stays classic BRT. See stock_analysis/BRT_LOGIC_SPEC.md.
rem max_market_cap=0 / min_market_cap=0: disable post-enrich cap filter (engine default is a huge >0
rem   bound). Same class of bug as AMD Closed wipe when Yahoo omits/returns odd caps. rocket_tbn also
rem   keeps trades when market_cap is None — bats must still pass 0 so the default bound cannot fire.
rem Extra CLI: trailing %* forwarded to rocket_tbn (leading .csv / ALL stripped; -v kept).
rem   run_brt.bat -v brt_like_wpbr=true
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

call "%~dp0tools\apply_universe_cli_arg.bat" BRT_UNIV_ARG %1 %2
call "%~dp0tools\build_cli_forward.bat" BRT_FORWARD "%BRT_UNIV_ARG%" %*
call "%~dp0tools\load_universe_csv.bat" BRT "%BRT_UNIV_ARG%"
if errorlevel 1 exit /b 1
echo [BRT] Universe src=%BRT_UNIVERSE_SRC% pass_s=%BRT_PASS_SYMBOLS%

if not defined PER_SYMBOL_SETTINGS set "PER_SYMBOL_SETTINGS=stock_analysis\Per_Symbol_Optimized_Settings_Approved_Latest.json"

set "PS_ARGS="
if exist "%~dp0%PER_SYMBOL_SETTINGS%" set "PS_ARGS=--per-symbol-settings %PER_SYMBOL_SETTINGS%"

if "%BRT_PASS_SYMBOLS%"=="1" (
  "%PY%" stock_analysis\rocket_tbn.py data\newdata\data -o drive -w 32 --no-regression --aggressive --print-zones -v stop_pct=0.934 -v target_pct=1.21 -v too_high_multiplier=0 -v band_pct=0.0154 -v strong_pre_pivot_pct=0.081 -v strong_post_pivot_pct=0.108 -v strong_pre_pivot_bars=7 -v strong_post_pivot_bars=7 -v breakout_bars=100 -v tight_range_threshold_pct=0.35 -v tight_range_lookback=105 -v sheet_breakout_scan_start_row_delta=2 -v brt_sheet_touch=true -v min_spy_compare_1y_at_trigger=-1000 -v sheet_red_to_green_entry_enabled=true -v sheet_dw_countif_include_prior_bar_date=false -v growth_filter_enabled=true -v min_ind_score=-1 -v compute_beta=true -v brt_zones=true -v yh_zones=false -v min_pivot_run_h_before_entry=0 -v min_beta_at_trigger=0 -v max_market_cap=0 -v min_market_cap=0 %PS_ARGS% -s "!BRT_SYMBOLS!" !BRT_FORWARD!
) else (
  "%PY%" stock_analysis\rocket_tbn.py data\newdata\data -o drive -w 32 --no-regression --aggressive --print-zones -v stop_pct=0.934 -v target_pct=1.21 -v too_high_multiplier=0 -v band_pct=0.0154 -v strong_pre_pivot_pct=0.081 -v strong_post_pivot_pct=0.108 -v strong_pre_pivot_bars=7 -v strong_post_pivot_bars=7 -v breakout_bars=100 -v tight_range_threshold_pct=0.35 -v tight_range_lookback=105 -v sheet_breakout_scan_start_row_delta=2 -v brt_sheet_touch=true -v min_spy_compare_1y_at_trigger=-1000 -v sheet_red_to_green_entry_enabled=true -v sheet_dw_countif_include_prior_bar_date=false -v growth_filter_enabled=true -v min_ind_score=-1 -v compute_beta=true -v brt_zones=true -v yh_zones=false -v min_pivot_run_h_before_entry=0 -v min_beta_at_trigger=0 -v max_market_cap=0 -v min_market_cap=0 %PS_ARGS% !BRT_FORWARD!
)
exit /b %errorlevel%
