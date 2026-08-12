@echo off
rem VEC (Volume + prior-period Extreme Confluence) — outputs VEC_* CSVs in drive\
rem Standalone: double-click or call from DailyRun.
rem Universe: drive\universes\VEC_universe.csv (one ticker per line)
rem Override: run_vec.bat path\to\test_universe.csv
rem          set VEC_UNIVERSE_CSV=...
rem          set VEC_SYMBOLS=AAPL,MSFT
rem Full universe (all data\newdata\data\*.csv) — no env vars:
rem   run_vec.bat ALL
rem   run_vec.bat --all
rem   run_vec.bat "*"          (quote * in PowerShell; bare * often expands)
rem Legacy env: set VEC_SYMBOLS=* / ALL / set VEC_ALL_CSV=1
rem Extra CLI: trailing %* forwarded to rocket_tbn (leading .csv / ALL stripped; -v kept).
rem   run_vec.bat -v vec_confluence_pct=0.01
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

call "%~dp0tools\apply_universe_cli_arg.bat" VEC_UNIV_ARG %1 %2
call "%~dp0tools\build_cli_forward.bat" VEC_FORWARD "%VEC_UNIV_ARG%" %*
call "%~dp0tools\load_universe_csv.bat" VEC "%VEC_UNIV_ARG%"
if errorlevel 1 exit /b 1
echo [VEC] Universe src=%VEC_UNIVERSE_SRC% pass_s=%VEC_PASS_SYMBOLS%

if "%VEC_PASS_SYMBOLS%"=="1" (
  "%PY%" stock_analysis\rocket_tbn.py data\newdata\data -o drive -w 16 --aggressive --use-duckdb --no-regression --print-zones -v vec_zones=true -v brt_zones=false -v yh_zones=false -v band_pct=0.012 -v vec_vp_lookback=60 -v vec_prior_bars=5 -v vec_confluence_pct=0.0075 -v vec_move_away_pct=0.02 -v min_spy_compare_1y_at_trigger=-1000 -v ind_score_weights_path="" -v too_high_multiplier=0 -v target_pct=1.24 -v stop_pct=0.927 -s "!VEC_SYMBOLS!" !VEC_FORWARD!
) else (
  "%PY%" stock_analysis\rocket_tbn.py data\newdata\data -o drive -w 16 --aggressive --use-duckdb --no-regression --print-zones -v vec_zones=true -v brt_zones=false -v yh_zones=false -v band_pct=0.012 -v vec_vp_lookback=60 -v vec_prior_bars=5 -v vec_confluence_pct=0.0075 -v vec_move_away_pct=0.02 -v min_spy_compare_1y_at_trigger=-1000 -v ind_score_weights_path="" -v too_high_multiplier=0 -v target_pct=1.24 -v stop_pct=0.927 !VEC_FORWARD!
)
exit /b %errorlevel%
