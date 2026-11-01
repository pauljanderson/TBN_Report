@echo off
REM RL exit-strategies A/B (research only). Prefer --priority for first pass.
setlocal
cd /d "%~dp0"
if not defined PY set "PY=python"
"%PY%" tools\rl_exit_strategies_ab.py --priority --skip-existing --jobs 3 --workers 12 %*
endlocal
