@echo off
rem Reconcile gate: frozen engine Closed vs latest DailyRun Closed (YH / BRT / WPBR / RS / SB / RL / VZ; MVCP retired).
rem Standalone: double-click or call from DailyRun after backtests + copy_latest.
rem Disable temporarily:
rem   set SKIP_RECONCILE_GATE=1
rem   set RECONCILE_GATE=0
rem Config: drive\paul_experiments\reconcile_gate_config.json
rem Docs:   drive\paul_experiments\yh_baseline_20260731\RECONCILE_GATE.md
rem YH freeze: drive\paul_experiments\yh_baseline_260824120350\README.md  (Mag9; growth fail-closed)
rem BRT freeze: drive\paul_experiments\brt_baseline_260824120321\README.md  (Mag10; pivots 10%/10%)
rem RS freeze: drive\paul_experiments\rs_baseline_260807141317\README.md
rem SB freeze: drive\paul_experiments\sb_baseline_260803184014\README.md
rem VZ: DailyRun official TBN sleeve; reconcile enabled (Paul78.142 + EXIT_atr4_s025_r15_ts20, PO adopt 2026-09-07;
rem     atr4=4% ATR floor at trigger close, not a 4-ATR stop; s025=zone.lo-0.25*ATR; r15=1.5R; ts20=20 bars;
rem     trigger-gate adopt 2026-09-07 after HOLD AB — entry gate off).
rem     One position per symbol (DailyRun lock 2026-09-15): latest side is VZ_LatestRun_Closed.csv;
rem     golden is the house pin after that lock (not the old pyramid 2708-trade book).
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
