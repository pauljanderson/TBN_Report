@echo off
rem Minervini VCP Stage-2 pivot breakout — NEW TBN mode (mvcp_mode)
rem Short alias: run_mvcp.bat (preferred). This file is the canonical implementation.
rem Engine: rocket_tbn.py + rocket_minervini_vcp.py
rem Outputs: drive\MVCP_*_<ts>.csv (+ EquityCurve_Aggressive when --aggressive)
rem Docs: drive\paul_experiments\tbn_new_systems\minervini_vcp\HOW_TO_RUN.html
rem
rem Host sizing (same as YH/BRT/RS Closed path via tbn_host_sizing):
rem   deployable = 500_000 × 2 × 0.6 = 600_000
rem   per_trade  = deployable / max_positions   (0 = auto peak concurrent)
rem Override max slots: set MVCP_MAX_POSITIONS=10  (passed as -v max_positions=N)
rem Disable aggressive overlay: set MVCP_AGGRESSIVE=false
rem Workers: set MVCP_WORKERS=12 (default) → -w; override with trailing -w N (%* last wins)
rem
rem Universe: drive\universes\MVCP_universe.csv (default * = full scan / omit -s)
rem Override: run_minervini_vcp.bat path\to\test_universe.csv
rem          set MVCP_UNIVERSE_CSV=...
rem          set MVCP_SYMBOLS=AAPL,MSFT
rem Full universe (all data\newdata\data\*.csv) — no env vars:
rem   run_minervini_vcp.bat ALL
rem   run_minervini_vcp.bat --all
rem   run_minervini_vcp.bat "*"   (quote * in PowerShell; bare * often expands)
rem Legacy env: set MVCP_SYMBOLS=* / ALL / set MVCP_ALL_CSV=1
rem          set MVCP_STOP=0.92  set MVCP_TARGET=1.25
rem Theory levers (defaults): RS>=80, depth_shrink=0.65, vol_breakout=1.5, stop<=8%%
rem Seed-stage reference list: drive\paul_experiments\tbn_new_systems\minervini_vcp\20_seed_universe.md
rem Extra CLI: trailing %* forwarded to rocket_tbn (except leading .csv / ALL universe override).
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1
if not defined MVCP_TARGET set "MVCP_TARGET=1.25"
if not defined MVCP_STOP set "MVCP_STOP=0.92"
if not defined MVCP_MAX_POSITIONS set "MVCP_MAX_POSITIONS=0"
if not defined MVCP_AGGRESSIVE set "MVCP_AGGRESSIVE=true"
if not defined MVCP_WORKERS set "MVCP_WORKERS=12"
set "MVCP_AGG_FLAG="
if /i "%MVCP_AGGRESSIVE%"=="true" set "MVCP_AGG_FLAG=--aggressive"
if /i "%MVCP_AGGRESSIVE%"=="1" set "MVCP_AGG_FLAG=--aggressive"
if /i "%MVCP_AGGRESSIVE%"=="yes" set "MVCP_AGG_FLAG=--aggressive"

call "%~dp0tools\apply_universe_cli_arg.bat" MVCP_UNIV_ARG %1 %2
set "MVCP_FORWARD=%*"
if not "%MVCP_UNIV_ARG%"=="" set "MVCP_FORWARD="
call "%~dp0tools\load_universe_csv.bat" MVCP "%MVCP_UNIV_ARG%"
if errorlevel 1 exit /b 1
echo [MVCP] Universe src=%MVCP_UNIVERSE_SRC% pass_s=%MVCP_PASS_SYMBOLS%

rem Neutralize peer systems; MVCP owns entry path.
if "%MVCP_PASS_SYMBOLS%"=="1" (
  "%PY%" stock_analysis\rocket_tbn.py data\newdata\data -o drive -w %MVCP_WORKERS% --no-regression %MVCP_AGG_FLAG% ^
    --initial-capital 500000 --aggressive-max-multiple 2.0 --margin-utilization 0.6 ^
    -v mvcp_mode=true -v brt_zones=false -v yh_zones=false -v wpbr_zones=false -v rl_mode=false ^
    -v relative_strength_enabled=false -v rs_mode=false -v indicator_buy=off ^
    -v target_pct=%MVCP_TARGET% -v stop_pct=%MVCP_STOP% -v stop_pct_is_multiplier=true ^
    -v mvcp_rs_min_percentile=80 -v mvcp_vol_breakout_mult=1.5 -v mvcp_depth_shrink=0.65 ^
    -v mvcp_rs_universe=data_dir -v symbol_reentry_cooldown_days=20 ^
    -v max_positions=%MVCP_MAX_POSITIONS% ^
    -s "!MVCP_SYMBOLS!" ^
    !MVCP_FORWARD!
) else (
  "%PY%" stock_analysis\rocket_tbn.py data\newdata\data -o drive -w %MVCP_WORKERS% --no-regression %MVCP_AGG_FLAG% ^
    --initial-capital 500000 --aggressive-max-multiple 2.0 --margin-utilization 0.6 ^
    -v mvcp_mode=true -v brt_zones=false -v yh_zones=false -v wpbr_zones=false -v rl_mode=false ^
    -v relative_strength_enabled=false -v rs_mode=false -v indicator_buy=off ^
    -v target_pct=%MVCP_TARGET% -v stop_pct=%MVCP_STOP% -v stop_pct_is_multiplier=true ^
    -v mvcp_rs_min_percentile=80 -v mvcp_vol_breakout_mult=1.5 -v mvcp_depth_shrink=0.65 ^
    -v mvcp_rs_universe=data_dir -v symbol_reentry_cooldown_days=20 ^
    -v max_positions=%MVCP_MAX_POSITIONS% ^
    !MVCP_FORWARD!
)
exit /b %errorlevel%
