@echo off
rem Reconcile gate: frozen engine Closed vs latest DailyRun Closed (YH / BRT / WPBR / RS / SB).
rem Standalone: double-click or call from DailyRun after backtests + copy_latest.
rem Disable temporarily:
rem   set SKIP_RECONCILE_GATE=1
rem   set RECONCILE_GATE=0
rem Config: drive\paul_experiments\reconcile_gate_config.json
rem Docs:   drive\paul_experiments\yh_baseline_20260731\RECONCILE_GATE.md
rem YH freeze: drive\paul_experiments\yh_baseline_260807183541\README.md  (Mag9 no TSLA)
rem RS freeze: drive\paul_experiments\rs_baseline_260807141317\README.md
rem SB freeze: drive\paul_experiments\sb_baseline_260803184014\README.md
rem MVCP: retired 2026-08-21 — config enabled:false (freeze archive kept)
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
