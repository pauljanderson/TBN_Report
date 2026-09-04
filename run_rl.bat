@echo off
rem Python Rocket Launcher (rl_mode=true) — outputs RL_Closed|Open|... in drive\
rem Standalone: double-click or call from DailyRun.
rem Universe: drive\universes\RL_universe.csv (one ticker per line)
rem Override: run_rl.bat path\to\test_universe.csv
rem          set RL_UNIVERSE_CSV=...
rem          set RL_SYMBOLS=AAPL,MSFT
rem Full universe (all data\newdata\data\*.csv) — no env vars:
rem   run_rl.bat ALL
rem   run_rl.bat --all
rem   run_rl.bat "*"          (quote * in PowerShell; bare * often expands)
rem Legacy env: set RL_SYMBOLS=* / ALL / set RL_ALL_CSV=1
rem Extra CLI: trailing %* forwarded to rocket_tbn (leading .csv / ALL stripped; -v kept).
rem   run_rl.bat -v aggressive_sell=average
rem   run_rl.bat -v "aggressive_sell=average"
rem   run_rl.bat ALL -v aggressive_sell=average
rem (CMD splits on '='; build_cli_forward.bat rejoins -v KEY VALUE → KEY=VALUE.)
rem Note: data\rl_gold_universe.txt is used by optimizer/parity — keep in sync with RL_universe.csv.
rem IND_TC_*: not on RL_Closed yet (separate writer; indicators only for mandatory/exclude gates).
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

call "%~dp0tools\apply_universe_cli_arg.bat" RL_UNIV_ARG %1 %2
call "%~dp0tools\build_cli_forward.bat" RL_FORWARD "%RL_UNIV_ARG%" %*
call "%~dp0tools\load_universe_csv.bat" RL "%RL_UNIV_ARG%"
if errorlevel 1 exit /b 1
echo [RL] Universe src=%RL_UNIVERSE_SRC% pass_s=%RL_PASS_SYMBOLS%

if not defined PER_SYMBOL_SETTINGS set "PER_SYMBOL_SETTINGS=stock_analysis\Per_Symbol_Optimized_Settings_Approved_Latest.json"

set "PS_ARGS="
if exist "%~dp0%PER_SYMBOL_SETTINGS%" set "PS_ARGS=--per-symbol-settings %PER_SYMBOL_SETTINGS%"

rem Production default: rl_too_high off (0); rl_dip_pct=1.055 (±5.5%);
rem cut_the_losers OFF (1000); timed exit +40% entry MTM then 30d (adopt 40_30d 20260831).
rem Per-symbol JSON also stores 0 for RL_TOO_HIGH on RL symbols.
rem Cheap analysis (ONE_LINER / FIT / ImproveHints) emits automatically after the run.
rem Charts + CRWD-style HTML (NOT in DailyRun): python stock_analysis\rl_post_run_analysis.py --stamp <ts> --charts
if "%RL_PASS_SYMBOLS%"=="1" (
  "%PY%" stock_analysis\rocket_tbn.py data\newdata\data -o drive -w 5 --aggressive --no-regression -v rl_mode=true -v brt_zones=false -v yh_zones=false -v indicator_buy=off -v rl_sma_qual=1 -v ATR_LOW=off -v ATR_HIGH=off -v rl_slope_threshold=0 -v rl_too_high=0 -v rl_dip_pct=1.055 -v rl_cut_the_losers=1000 -v rl_exit_percent=0.40 -v rl_exit_days=30 %PS_ARGS% -s "!RL_SYMBOLS!" !RL_FORWARD!
) else (
  "%PY%" stock_analysis\rocket_tbn.py data\newdata\data -o drive -w 5 --aggressive --no-regression -v rl_mode=true -v brt_zones=false -v yh_zones=false -v indicator_buy=off -v rl_sma_qual=1 -v ATR_LOW=off -v ATR_HIGH=off -v rl_slope_threshold=0 -v rl_too_high=0 -v rl_dip_pct=1.055 -v rl_cut_the_losers=1000 -v rl_exit_percent=0.40 -v rl_exit_days=30 %PS_ARGS% !RL_FORWARD!
)
exit /b %errorlevel%
