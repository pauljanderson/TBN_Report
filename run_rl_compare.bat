@echo off
rem Compare AWK vs Python RL outputs (DailyRun parity gate).
rem Usage: run_rl_compare.bat <awk_ts> <python_ts> [not_before_yyMMddHHmmss]
rem   e.g. run_rl_compare.bat 260707150123 260707150224
rem   e.g. run_rl_compare.bat 260707150123 260707150224 260707144900
rem Optional 3rd arg or env DAILYRUN_START_TS: refuse stamps older than DailyRun start.
setlocal EnableExtensions
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1
if "%~1"=="" (
  echo ERROR: run_rl_compare.bat requires AWK and Python timestamps 1>&2
  echo Usage: run_rl_compare.bat AWK_TS PYTHON_TS [NOT_BEFORE] 1>&2
  exit /b 1
)
if "%~2"=="" (
  echo ERROR: run_rl_compare.bat requires AWK and Python timestamps 1>&2
  echo Usage: run_rl_compare.bat AWK_TS PYTHON_TS [NOT_BEFORE] 1>&2
  exit /b 1
)
set "NOT_BEFORE=%~3"
if not defined NOT_BEFORE if defined DAILYRUN_START_TS set "NOT_BEFORE=%DAILYRUN_START_TS%"
if defined NOT_BEFORE (
  "%PY%" tools\compare_rl_engine_outputs.py --output-dir drive --awk-ts %~1 --python-ts %~2 --not-before %NOT_BEFORE%
) else (
  "%PY%" tools\compare_rl_engine_outputs.py --output-dir drive --awk-ts %~1 --python-ts %~2
)
exit /b %errorlevel%
