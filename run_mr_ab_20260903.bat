@echo off
rem Mean-reversion AB suite 2026-09-03 (research-only; not DailyRun).
rem Runs 3 overlays + BRT zscore exit engine AB, then rollup HTML.
setlocal EnableExtensions
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

echo === MR AB1 RL RSI(2) gate ===
"%PY%" tools\mr_rl_rsi2_gate_ab.py
if errorlevel 1 exit /b 1

echo === MR AB2 BRT recent loser ===
"%PY%" tools\mr_brt_recent_loser_ab.py
if errorlevel 1 exit /b 1

echo === MR AB3 RL Valuation dual-book ===
"%PY%" tools\mr_rl_valuation_dualbook_ab.py
if errorlevel 1 exit /b 1

echo === MR AB4 BRT zscore exit ===
"%PY%" tools\mr_brt_zscore_exit_ab.py %*
if errorlevel 1 exit /b 1

echo === Rollup ===
"%PY%" tools\mr_ab_rollup_20260903.py
if errorlevel 1 exit /b 1

echo DONE mean_reversion_ab_20260903
exit /b 0
