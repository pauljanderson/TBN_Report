@echo off
rem Reconcile gate: frozen engine Closed vs latest DailyRun Closed (YH / BRT / WPBR / RS / SB).
rem Standalone: double-click or call from DailyRun after backtests + copy_latest.
rem Disable temporarily:
rem   set SKIP_RECONCILE_GATE=1
rem   set RECONCILE_GATE=0
rem Config: drive\paul_experiments\reconcile_gate_config.json
rem Docs:   drive\paul_experiments\yh_baseline_20260731\RECONCILE_GATE.md
rem RS freeze: drive\paul_experiments\rs_baseline_260801111512\README.md
rem SB freeze: drive\paul_experiments\sb_baseline_260803184014\README.md
setlocal EnableExtensions
cd /d "%~dp0"

if /i "%SKIP_RECONCILE_GATE%"=="1" (
  echo RECONCILE GATE SKIPPED ^(SKIP_RECONCILE_GATE=1^)
  exit /b 0
)
if /i "%RECONCILE_GATE%"=="0" (
  echo RECONCILE GATE SKIPPED ^(RECONCILE_GATE=0^)
  exit /b 0
)

if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

"%PY%" tools\reconcile_gate.py %*
exit /b %errorlevel%
