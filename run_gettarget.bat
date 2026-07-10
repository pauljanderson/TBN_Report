@echo off
rem Live stop/target for open positions — params aligned with run_brt.bat / run_ind.bat / run_yh.bat / run_rl.bat
setlocal EnableExtensions
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1
call "%~dp0daily_run_env.bat"
set "PS_ARGS="
if exist "%~dp0%PER_SYMBOL_SETTINGS%" set "PS_ARGS=--per-symbol-settings %PER_SYMBOL_SETTINGS%"
"%PY%" "%~dp0getTarget.py" ^
  --brt-atr-target=0 ^
  --brt-atr-stop=0 ^
  --brt-atr-increment=0 ^
  --brt-atr-progress=0 ^
  --brt-atr-days=0 ^
  "--brt-target-pct=1.21" ^
  "--brt-stop-pct=0.934" ^
  --ind-atr-target=2.0 ^
  --ind-atr-stop=1.2 ^
  --ind-atr-increment=0 ^
  --ind-atr-progress=0 ^
  --ind-atr-days=0 ^
  "--ind-target-pct=1.21" ^
  "--ind-stop-pct=0.903" ^
  --yh-atr-target=0 ^
  --yh-atr-stop=0 ^
  --yh-atr-increment=0 ^
  --yh-atr-progress=0 ^
  --yh-atr-days=0 ^
  "--yh-target-pct=1.27" ^
  "--yh-stop-pct=0.923" ^
  "--rl-target-pct=1.20" ^
  "--rl-stop-pct=0.934" ^
  --rl-use-sma50 ^
  %PS_ARGS%
exit /b %errorlevel%
