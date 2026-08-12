@echo off
rem WRL — Weekly Range / Swing demand-zone breakout (research sleeve)
rem Engine: rocket_tbn.py + rocket_wrl.py  (-v wrl_mode=true)
rem Outputs: drive\WRL_*_<ts>.csv (Closed / Open / Watchlist / Scanner / Summary / Audit / Equity)
rem Docs: docs\systems\wrl.html
rem
rem Levels: previous completed week high/low = range; walk back weekly for a higher high
rem (swing high) and a lower low (swing low). Watch when daily close is in
rem [swing_low, range_low]; buy next day if price trades up through range_low.
rem Targets: range high then swing high (default scale 50/50).
rem
rem Universe: drive\universes\WRL_universe.csv if present; else Mag10 default below.
rem Override: run_wrl.bat path\to\test_universe.csv
rem          set WRL_UNIVERSE_CSV=...
rem          set WRL_SYMBOLS=AAPL,MSFT
rem Full universe: run_wrl.bat ALL
rem Extra CLI: trailing %* forwarded to rocket_tbn ( -v wrl_target_mode=range|swing|scale )
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1
if not defined WRL_TARGET_MODE set "WRL_TARGET_MODE=scale"
if not defined WRL_STOP set "WRL_STOP=1.0"
if not defined WRL_MAX_POSITIONS set "WRL_MAX_POSITIONS=0"
if not defined WRL_AGGRESSIVE set "WRL_AGGRESSIVE=true"
if not defined WRL_WORKERS set "WRL_WORKERS=12"
set "WRL_AGG_FLAG="
if /i "%WRL_AGGRESSIVE%"=="true" set "WRL_AGG_FLAG=--aggressive"
if /i "%WRL_AGGRESSIVE%"=="1" set "WRL_AGG_FLAG=--aggressive"
if /i "%WRL_AGGRESSIVE%"=="yes" set "WRL_AGG_FLAG=--aggressive"

call "%~dp0tools\apply_universe_cli_arg.bat" WRL_UNIV_ARG %1 %2
call "%~dp0tools\build_cli_forward.bat" WRL_FORWARD "%WRL_UNIV_ARG%" %*
call "%~dp0tools\load_universe_csv.bat" WRL "%WRL_UNIV_ARG%"
if errorlevel 1 exit /b 1
if /i "%WRL_UNIVERSE_SRC%"=="missing" (
  set "WRL_SYMBOLS=AAPL,AMD,AMZN,AU,GOOGL,META,MSFT,NFLX,NVDA,TSLA"
  set "WRL_PASS_SYMBOLS=1"
  set "WRL_UNIVERSE_SRC=default_mag10"
)
echo [WRL] Universe src=%WRL_UNIVERSE_SRC% pass_s=%WRL_PASS_SYMBOLS% target_mode=%WRL_TARGET_MODE%

if "%WRL_PASS_SYMBOLS%"=="1" (
  "%PY%" stock_analysis\rocket_tbn.py data\newdata\data -o drive -w %WRL_WORKERS% --no-regression %WRL_AGG_FLAG% ^
    --initial-capital 500000 --aggressive-max-multiple 2.0 --margin-utilization 0.6 ^
    -v wrl_mode=true -v brt_zones=false -v yh_zones=false -v wpbr_zones=false -v vec_zones=false ^
    -v rl_mode=false -v relative_strength_enabled=false -v rs_mode=false -v indicator_buy=off ^
    -v mvcp_mode=false -v sb_mode=false -v qull_mode=false -v vz_mode=false ^
    -v wrl_target_mode=%WRL_TARGET_MODE% -v stop_pct=%WRL_STOP% -v stop_pct_is_multiplier=true ^
    -v max_positions=%WRL_MAX_POSITIONS% ^
    -s "!WRL_SYMBOLS!" ^
    !WRL_FORWARD!
) else (
  "%PY%" stock_analysis\rocket_tbn.py data\newdata\data -o drive -w %WRL_WORKERS% --no-regression %WRL_AGG_FLAG% ^
    --initial-capital 500000 --aggressive-max-multiple 2.0 --margin-utilization 0.6 ^
    -v wrl_mode=true -v brt_zones=false -v yh_zones=false -v wpbr_zones=false -v vec_zones=false ^
    -v rl_mode=false -v relative_strength_enabled=false -v rs_mode=false -v indicator_buy=off ^
    -v mvcp_mode=false -v sb_mode=false -v qull_mode=false -v vz_mode=false ^
    -v wrl_target_mode=%WRL_TARGET_MODE% -v stop_pct=%WRL_STOP% -v stop_pct_is_multiplier=true ^
    -v max_positions=%WRL_MAX_POSITIONS% ^
    !WRL_FORWARD!
)
exit /b %errorlevel%
