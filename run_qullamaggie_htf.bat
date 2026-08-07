@echo off
rem Qullamaggie High Tight Flag (HTF) + EP proxy — NEW TBN mode (qull_mode)
rem Short alias: run_qull.bat (preferred). This file is the canonical implementation.
rem Engine: rocket_tbn.py + rocket_qull_htf.py
rem Outputs: drive\QULL_*_<ts>.csv
rem Docs: drive\paul_experiments\tbn_new_systems\qull_ep_htf\HOW_TO_RUN.html
rem
rem Host sizing (same as YH/BRT/RS via tbn_host_sizing):
rem   deployable = 500_000 × 2 × 0.6 = 600_000
rem   per_trade  = deployable / max_positions   (0 = auto peak concurrent)
rem
rem Universe: drive\universes\QULL_universe.csv (default * = full scan / omit -s)
rem Override: run_qullamaggie_htf.bat path\to\test_universe.csv
rem          set QULL_UNIVERSE_CSV=...
rem          set QULL_SYMBOLS=AAPL,MSFT
rem Full universe (all data\newdata\data\*.csv) — no env vars:
rem   run_qullamaggie_htf.bat ALL
rem   run_qullamaggie_htf.bat --all
rem   run_qullamaggie_htf.bat "*"   (quote * in PowerShell; bare * often expands)
rem Legacy env: set QULL_SYMBOLS=* / ALL / set QULL_ALL_CSV=1
rem Extra CLI: trailing %* forwarded to rocket_tbn (except leading .csv / ALL universe override).
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

rem === EDIT DEFAULTS HERE ===
if not defined QULL_SETUP set "QULL_SETUP=htf"
if not defined QULL_PRIOR_RUN set "QULL_PRIOR_RUN=0.50"
if not defined QULL_COIL_BARS set "QULL_COIL_BARS=10"
if not defined QULL_COIL_RANGE set "QULL_COIL_RANGE=0.15"
if not defined QULL_TRAIL_EMA set "QULL_TRAIL_EMA=10"
if not defined QULL_VOL_BO set "QULL_VOL_BO=1.5"
if not defined QULL_MAX_POSITIONS set "QULL_MAX_POSITIONS=0"
if not defined QULL_AGGRESSIVE set "QULL_AGGRESSIVE=true"
if not defined QULL_WORKERS set "QULL_WORKERS=12"
rem === END EDIT DEFAULTS ===

set "QULL_AGG_FLAG="
if /i "%QULL_AGGRESSIVE%"=="true" set "QULL_AGG_FLAG=--aggressive"
if /i "%QULL_AGGRESSIVE%"=="1" set "QULL_AGG_FLAG=--aggressive"
if /i "%QULL_AGGRESSIVE%"=="yes" set "QULL_AGG_FLAG=--aggressive"

call "%~dp0tools\apply_universe_cli_arg.bat" QULL_UNIV_ARG %1 %2
set "QULL_FORWARD=%*"
if not "%QULL_UNIV_ARG%"=="" set "QULL_FORWARD="
call "%~dp0tools\load_universe_csv.bat" QULL "%QULL_UNIV_ARG%"
if errorlevel 1 exit /b 1
echo [QULL] Universe src=%QULL_UNIVERSE_SRC% pass_s=%QULL_PASS_SYMBOLS%

echo [QULL] qull_mode setup=%QULL_SETUP% prior_run=%QULL_PRIOR_RUN% coil=%QULL_COIL_BARS%/%QULL_COIL_RANGE% trail_ema=%QULL_TRAIL_EMA%
if "%QULL_PASS_SYMBOLS%"=="1" (
  "%PY%" stock_analysis\rocket_tbn.py data\newdata\data -o drive -w %QULL_WORKERS% --no-regression %QULL_AGG_FLAG% ^
    --initial-capital 500000 --aggressive-max-multiple 2.0 --margin-utilization 0.6 ^
    -v qull_mode=true -v brt_zones=false -v yh_zones=false -v wpbr_zones=false -v rl_mode=false ^
    -v relative_strength_enabled=false -v rs_mode=false -v indicator_buy=off -v sb_mode=false -v mvcp_mode=false ^
    -v qull_setup=%QULL_SETUP% -v qull_prior_run_pct=%QULL_PRIOR_RUN% ^
    -v qull_coil_bars=%QULL_COIL_BARS% -v qull_coil_range_pct=%QULL_COIL_RANGE% ^
    -v qull_trail_ema=%QULL_TRAIL_EMA% -v qull_vol_breakout_mult=%QULL_VOL_BO% ^
    -v qull_market_filter=true -v symbol_reentry_cooldown_days=5 ^
    -v max_positions=%QULL_MAX_POSITIONS% ^
    -s "!QULL_SYMBOLS!" ^
    !QULL_FORWARD!
) else (
  "%PY%" stock_analysis\rocket_tbn.py data\newdata\data -o drive -w %QULL_WORKERS% --no-regression %QULL_AGG_FLAG% ^
    --initial-capital 500000 --aggressive-max-multiple 2.0 --margin-utilization 0.6 ^
    -v qull_mode=true -v brt_zones=false -v yh_zones=false -v wpbr_zones=false -v rl_mode=false ^
    -v relative_strength_enabled=false -v rs_mode=false -v indicator_buy=off -v sb_mode=false -v mvcp_mode=false ^
    -v qull_setup=%QULL_SETUP% -v qull_prior_run_pct=%QULL_PRIOR_RUN% ^
    -v qull_coil_bars=%QULL_COIL_BARS% -v qull_coil_range_pct=%QULL_COIL_RANGE% ^
    -v qull_trail_ema=%QULL_TRAIL_EMA% -v qull_vol_breakout_mult=%QULL_VOL_BO% ^
    -v qull_market_filter=true -v symbol_reentry_cooldown_days=5 ^
    -v max_positions=%QULL_MAX_POSITIONS% ^
    !QULL_FORWARD!
)
set "RC=%errorlevel%"
if not "%RC%"=="0" (
  echo [QULL] FAILED errorlevel=%RC%
  exit /b %RC%
)
exit /b 0
