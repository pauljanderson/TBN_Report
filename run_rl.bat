@echo off
rem Python Rocket Launcher (rl_mode=true) — outputs RL_Closed|Open|... in drive\
rem Override symbols: set RL_SYMBOLS=SYM1,SYM2 before calling
setlocal EnableExtensions
cd /d "%~dp0"
call "%~dp0daily_run_env.bat"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1
set "PS_ARGS="
if exist "%~dp0%PER_SYMBOL_SETTINGS%" set "PS_ARGS=--per-symbol-settings %PER_SYMBOL_SETTINGS%"
"%PY%" stock_analysis\rocket_brt.py data\newdata\data -o drive -w 5 --no-regression -v rl_mode=true -v brt_zones=false -v yh_zones=false -v indicator_buy=off %PS_ARGS% -s "%RL_SYMBOLS%"
exit /b %errorlevel%
