@echo off
rem Compare AWK vs Python RL outputs (DailyRun parity gate).
rem Usage: run_rl_compare.bat <awk_ts> <python_ts>
rem   e.g. run_rl_compare.bat 260707150123 260707150224
setlocal EnableExtensions
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1
if "%~1"=="" (
  echo ERROR: run_rl_compare.bat requires AWK and Python timestamps 1>&2
  echo Usage: run_rl_compare.bat AWK_TS PYTHON_TS 1>&2
  exit /b 1
)
if "%~2"=="" (
  echo ERROR: run_rl_compare.bat requires AWK and Python timestamps 1>&2
  echo Usage: run_rl_compare.bat AWK_TS PYTHON_TS 1>&2
  exit /b 1
)
"%PY%" tools\compare_rl_engine_outputs.py --output-dir drive --awk-ts %~1 --python-ts %~2
exit /b %errorlevel%
