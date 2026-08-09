@echo off
rem StockBee Momentum Burst ??? TBN host mode (sb_mode)
rem Short alias: run_sb.bat (preferred). This file is the canonical implementation.
rem Engine: rocket_tbn.py + rocket_stockbee_burst.py (Closed/Open/Audit via BRT writers)
rem Outputs: drive\SB_*_<ts>.csv (+ EquityCurve_Aggressive when --aggressive)
rem Docs: drive\paul_experiments\tbn_new_systems\stockbee_momentum_burst\HOW_TO_RUN.html
rem
rem Universe: drive\universes\SB_universe.csv (one ticker per line; gold 56)
rem Override: run_stockbee_burst.bat path\to\test_universe.csv
rem          set SB_UNIVERSE_CSV=...
rem          set SB_SYMBOLS=AAPL,MSFT
rem Full universe (all data\newdata\data\*.csv) — no env vars:
rem   run_stockbee_burst.bat ALL
rem   run_stockbee_burst.bat --all
rem   run_stockbee_burst.bat "*"          (quote * in PowerShell; bare * often expands)
rem Legacy env still works: set SB_SYMBOLS=* / ALL / set SB_ALL_CSV=1
rem Legacy: GOLD_UNIVERSE.csv (one-line comma list) still used by older AB bats.
rem
rem ONE-LINER (gold 56-name production list — same CLI shape as run_rs / run_brt):
rem   run_sb.bat
rem
rem Default sizing = rocket_tbn host parity (NOT Seed-opt $100R):
rem   deployable = initial_capital ?? aggressive_max_multiple ?? margin_utilization
rem              = 500_000 ?? 2 ?? 0.6 = 600_000
rem   per_trade  = deployable / max_positions   (0 = auto peak concurrent)
rem   --aggressive: EquityCurve_Aggressive_* via BRT_DrawdownCalc (same as YH/BRT/RS)
rem Optional research path: set SB_SIZE_FROM_STOP=true (skips host dollar-scale)
rem
rem Other overrides before calling:
rem   set SB_TARGET=1.097
rem   set SB_TIME_STOP=5
rem   set SB_NO_FT=3
rem   set SB_MAX_RISK=0.078
rem   set SB_SIZE_FROM_STOP=true
rem   set SB_RISK_FRAC=0.01
rem   set SB_MAX_POSITIONS=0
rem   set SB_AGGRESSIVE=false
rem Working defaults: target=1.097, max_risk=0.078 (was Seed-opt 1.10 / 0.08).
rem Theory v1 freeze remains 0.03 historically; override SB_MAX_RISK to restore.
rem Reconcile baseline: sb_baseline_260803184014 (gold-56 @ 1.097/0.078).
rem Prior sb_baseline_260803121109 (1.10/0.08) is obsolete.
rem Extra CLI: trailing %* forwarded to rocket_tbn (except leading .csv / ALL universe override).

setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

if not defined SB_TARGET set "SB_TARGET=1.097"
if not defined SB_TIME_STOP set "SB_TIME_STOP=5"
if not defined SB_NO_FT set "SB_NO_FT=3"
if not defined SB_MAX_RISK set "SB_MAX_RISK=0.078"
if not defined SB_SIZE_FROM_STOP set "SB_SIZE_FROM_STOP=false"
if not defined SB_RISK_FRAC set "SB_RISK_FRAC=0.01"
if not defined SB_MAX_POSITIONS set "SB_MAX_POSITIONS=0"
if not defined SB_AGGRESSIVE set "SB_AGGRESSIVE=true"
if not defined SB_WORKERS set "SB_WORKERS=5"

set "SB_AGG_FLAG="
if /i "%SB_AGGRESSIVE%"=="true" set "SB_AGG_FLAG=--aggressive"
if /i "%SB_AGGRESSIVE%"=="1" set "SB_AGG_FLAG=--aggressive"
if /i "%SB_AGGRESSIVE%"=="yes" set "SB_AGG_FLAG=--aggressive"

rem Optional leading universe override (do not forward that arg to rocket_tbn)
call "%~dp0tools\apply_universe_cli_arg.bat" SB_UNIV_ARG %1 %2
set "SB_FORWARD=%*"
if not "%SB_UNIV_ARG%"=="" set "SB_FORWARD="
call "%~dp0tools\load_universe_csv.bat" SB "%SB_UNIV_ARG%"
if errorlevel 1 exit /b 1
echo [SB] Universe src=%SB_UNIVERSE_SRC% pass_s=%SB_PASS_SYMBOLS%
rem Loud WARN whenever -s will be omitted (full data CSV scan)
if not "%SB_PASS_SYMBOLS%"=="1" (
  echo [SB] WARN: pass_s=0 — omitting -s ^(FULL data CSV scan^). src=%SB_UNIVERSE_SRC%
  echo [SB] WARN: Production default is gold-56 via drive\universes\SB_universe.csv. Intentional full scan: run_sb.bat ALL
)
if /i "!SB_SYMBOLS!"=="*" (
  echo [SB] WARN: SB_SYMBOLS=* - scanning FULL data CSVs, not gold-56. Unset SB_SYMBOLS for production gold run.
)
if /i "!SB_SYMBOLS!"=="ALL" (
  echo [SB] WARN: SB_SYMBOLS=ALL - scanning FULL data CSVs, not gold-56. Unset SB_SYMBOLS for production gold run.
)
if "!SB_ALL_CSV!"=="1" (
  echo [SB] WARN: SB_ALL_CSV=1 - scanning FULL data CSVs, not gold-56. Unset SB_ALL_CSV for production gold run.
)
if /i "%SB_UNIVERSE_SRC%"=="missing" (
  echo [SB] ERROR: drive\universes\SB_universe.csv missing — refusing silent full-universe fallback.
  echo [SB] ERROR: Restore SB_universe.csv or pass an explicit CSV / run_sb.bat ALL.
  exit /b 1
)
if /i "!SB_SYMBOLS!" EQU "-s" (
  echo ERROR: SB_SYMBOLS is the flag -s — pass the ticker list, e.g. set SB_SYMBOLS=AAPL,NVDA
  exit /b 1
)
if /i "!SB_SYMBOLS!" EQU "--symbol" (
  echo ERROR: SB_SYMBOLS is the flag --symbol — pass the ticker list
  exit /b 1
)
if "%SB_PASS_SYMBOLS%"=="1" (
  set "_SB_N=0"
  for %%T in (!SB_SYMBOLS!) do set /a _SB_N+=1
  echo [SB] Whitelist tickers=!_SB_N! ^(pass -s^)
  set "_SB_N="
)

rem Neutralize peer systems; SB owns entry path via sb_mode.
if "%SB_PASS_SYMBOLS%"=="1" (
  "%PY%" stock_analysis\rocket_tbn.py data\newdata\data -o drive -w %SB_WORKERS% --no-regression %SB_AGG_FLAG% ^
    --initial-capital 500000 --aggressive-max-multiple 2.0 --margin-utilization 0.6 ^
    -v sb_mode=true -v brt_zones=false -v yh_zones=false -v wpbr_zones=false -v rl_mode=false ^
    -v relative_strength_enabled=false -v rs_mode=false -v mvcp_mode=false -v indicator_buy=off ^
    -v target_pct=%SB_TARGET% ^
    -v burst_time_stop_days=%SB_TIME_STOP% ^
    -v burst_no_ft_days=%SB_NO_FT% ^
    -v burst_max_risk_pct=%SB_MAX_RISK% ^
    -v burst_size_from_stop=%SB_SIZE_FROM_STOP% ^
    -v burst_risk_frac=%SB_RISK_FRAC% ^
    -v max_positions=%SB_MAX_POSITIONS% ^
    -v burst_min_pct=0.04 ^
    -v burst_dcr_min=0.70 ^
    -v burst_range_lookback=5 ^
    -v burst_vol_gt_prior=true ^
    -v burst_fill=next_open ^
    -v burst_mm_gate=false ^
    -v burst_max_prior_up_days=1 ^
    -v burst_min_price=5 ^
    -s "!SB_SYMBOLS!" ^
    !SB_FORWARD!
) else (
  "%PY%" stock_analysis\rocket_tbn.py data\newdata\data -o drive -w %SB_WORKERS% --no-regression %SB_AGG_FLAG% ^
    --initial-capital 500000 --aggressive-max-multiple 2.0 --margin-utilization 0.6 ^
    -v sb_mode=true -v brt_zones=false -v yh_zones=false -v wpbr_zones=false -v rl_mode=false ^
    -v relative_strength_enabled=false -v rs_mode=false -v mvcp_mode=false -v indicator_buy=off ^
    -v target_pct=%SB_TARGET% ^
    -v burst_time_stop_days=%SB_TIME_STOP% ^
    -v burst_no_ft_days=%SB_NO_FT% ^
    -v burst_max_risk_pct=%SB_MAX_RISK% ^
    -v burst_size_from_stop=%SB_SIZE_FROM_STOP% ^
    -v burst_risk_frac=%SB_RISK_FRAC% ^
    -v max_positions=%SB_MAX_POSITIONS% ^
    -v burst_min_pct=0.04 ^
    -v burst_dcr_min=0.70 ^
    -v burst_range_lookback=5 ^
    -v burst_vol_gt_prior=true ^
    -v burst_fill=next_open ^
    -v burst_mm_gate=false ^
    -v burst_max_prior_up_days=1 ^
    -v burst_min_price=5 ^
    !SB_FORWARD!
)
exit /b %errorlevel%
