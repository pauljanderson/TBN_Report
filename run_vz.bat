@echo off
rem VZ (Volume Zone) - break and retest RESEARCH sleeve via TBN host (vz_mode)
rem Engine: rocket_tbn.py -v vz_mode=true -> stock_analysis\rocket_vz.py
rem         (tools\vol_zone_break_retest.py freeze RESEARCH_CANDIDATE_V2_RW63 + zone_atr05_ts40)
rem Outputs: drive\VZ_*_<ts>.csv - Closed/Audit/Report match RS/SB wide TBN schema
rem Docs: drive\paul_experiments\VZ_System_Guide.html
rem       drive\paul_experiments\VZ_TBN_Integration_And_Predictive_Timing.html
rem       drive\paul_experiments\tbn_new_systems\volume_zone\HOW_TO_RUN.md
rem
rem Freeze (research - do not retune on OOS):
rem   HL-only, first_retest_only=true, min_touches>=1, retest_eps_pct=0.005
rem   lookback=126, retest_window=63, exit=zone_atr05_ts40
rem   entry_on=next_open (predictive: signal bar T close -> buy T+1 open; never T open)
rem
rem Universe: drive\universes\VZ_universe.csv (DualPaul78 83-name research default)
rem Override: run_vz.bat path\to\test_universe.csv
rem          set VZ_UNIVERSE_CSV=...
rem          set VZ_SYMBOLS=AAPL,MSFT
rem Full universe: run_vz.bat ALL / --all / "*"
rem Workers: set VZ_WORKERS=12
rem Extra CLI: trailing %* forwarded to rocket_tbn (-v KEY=VALUE kept).
rem
rem DailyRun: NOT wired by default (research sleeve).

setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

if not defined VZ_LOOKBACK set "VZ_LOOKBACK=126"
if not defined VZ_RETEST_WINDOW set "VZ_RETEST_WINDOW=63"
if not defined VZ_RETEST_EPS set "VZ_RETEST_EPS=0.005"
if not defined VZ_MIN_TOUCHES set "VZ_MIN_TOUCHES=1"
if not defined VZ_ENTRY_ON set "VZ_ENTRY_ON=next_open"
if not defined VZ_EXIT_NAME set "VZ_EXIT_NAME=zone_atr05_ts40"
if not defined VZ_EXIT_BARS set "VZ_EXIT_BARS=40"
if not defined VZ_TARGET_R set "VZ_TARGET_R=2.0"
if not defined VZ_STOP_ATR set "VZ_STOP_ATR=0.5"
if not defined VZ_AGGRESSIVE set "VZ_AGGRESSIVE=true"
if not defined VZ_WORKERS set "VZ_WORKERS=12"

set "VZ_AGG_FLAG="
if /i "%VZ_AGGRESSIVE%"=="true" set "VZ_AGG_FLAG=--aggressive"
if /i "%VZ_AGGRESSIVE%"=="1" set "VZ_AGG_FLAG=--aggressive"
if /i "%VZ_AGGRESSIVE%"=="yes" set "VZ_AGG_FLAG=--aggressive"

call "%~dp0tools\apply_universe_cli_arg.bat" VZ_UNIV_ARG %1 %2
call "%~dp0tools\build_cli_forward.bat" VZ_FORWARD "%VZ_UNIV_ARG%" %*
call "%~dp0tools\load_universe_csv.bat" VZ "%VZ_UNIV_ARG%"
if errorlevel 1 exit /b 1
echo [VZ] RESEARCH sleeve via TBN vz_mode - Universe src=%VZ_UNIVERSE_SRC% pass_s=%VZ_PASS_SYMBOLS%
echo [VZ] freeze lookback=%VZ_LOOKBACK% rw=%VZ_RETEST_WINDOW% entry_on=%VZ_ENTRY_ON% exit=%VZ_EXIT_NAME% workers=%VZ_WORKERS%

if /i "%VZ_UNIVERSE_SRC%"=="missing" (
  echo [VZ] ERROR: drive\universes\VZ_universe.csv missing - refusing silent full-universe fallback.
  echo [VZ] ERROR: Restore VZ_universe.csv or pass an explicit CSV / run_vz.bat ALL.
  exit /b 1
)

rem Neutralize peer systems; VZ owns entry path via vz_mode.
rem One-line invokes (like run_rs.bat): blank lines after ^ break CMD continuation.
if "%VZ_PASS_SYMBOLS%"=="1" (
  "%PY%" stock_analysis\rocket_tbn.py data\newdata\data -o drive -w %VZ_WORKERS% --no-regression %VZ_AGG_FLAG% --initial-capital 500000 --aggressive-max-multiple 2.0 --margin-utilization 0.6 -v vz_mode=true -v brt_zones=false -v yh_zones=false -v wpbr_zones=false -v rl_mode=false -v relative_strength_enabled=false -v rs_mode=false -v mvcp_mode=false -v sb_mode=false -v qull_mode=false -v indicator_buy=off -v vz_lookback_days=%VZ_LOOKBACK% -v vz_retest_window=%VZ_RETEST_WINDOW% -v vz_retest_eps_pct=%VZ_RETEST_EPS% -v vz_first_retest_only=true -v vz_min_touches_before_entry=%VZ_MIN_TOUCHES% -v vz_entry_on=%VZ_ENTRY_ON% -v vz_zone_kinds=HL -v vz_exit_name=%VZ_EXIT_NAME% -v vz_exit_bars=%VZ_EXIT_BARS% -v vz_target_r=%VZ_TARGET_R% -v vz_stop_atr_buffer=%VZ_STOP_ATR% -v vz_sheet_notional=45000 -s "!VZ_SYMBOLS!" !VZ_FORWARD!
) else (
  "%PY%" stock_analysis\rocket_tbn.py data\newdata\data -o drive -w %VZ_WORKERS% --no-regression %VZ_AGG_FLAG% --initial-capital 500000 --aggressive-max-multiple 2.0 --margin-utilization 0.6 -v vz_mode=true -v brt_zones=false -v yh_zones=false -v wpbr_zones=false -v rl_mode=false -v relative_strength_enabled=false -v rs_mode=false -v mvcp_mode=false -v sb_mode=false -v qull_mode=false -v indicator_buy=off -v vz_lookback_days=%VZ_LOOKBACK% -v vz_retest_window=%VZ_RETEST_WINDOW% -v vz_retest_eps_pct=%VZ_RETEST_EPS% -v vz_first_retest_only=true -v vz_min_touches_before_entry=%VZ_MIN_TOUCHES% -v vz_entry_on=%VZ_ENTRY_ON% -v vz_zone_kinds=HL -v vz_exit_name=%VZ_EXIT_NAME% -v vz_exit_bars=%VZ_EXIT_BARS% -v vz_target_r=%VZ_TARGET_R% -v vz_stop_atr_buffer=%VZ_STOP_ATR% -v vz_sheet_notional=45000 !VZ_FORWARD!
)
exit /b %errorlevel%

