@echo off
REM RL too_high fill-gate A/B (research only). Cut-the-losers OFF on all arms.
setlocal
cd /d "%~dp0"
if not defined PY set "PY=python"
"%PY%" tools\rl_too_high_ab.py --skip-existing --jobs 3 --workers 12 %*
endlocal
