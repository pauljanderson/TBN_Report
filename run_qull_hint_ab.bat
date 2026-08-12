@echo off
rem QULL ImprovePriority / chart-SMA50 A/B on production baseline.
rem Control = run_qull.bat (HTF prior=0.50 coil=10/0.15 trail=10).
rem One knob / coherent skip per arm. Docs: docs\HYPOTHESIS_TEST.md
rem
rem Usage:
rem   run_qull_hint_ab.bat
rem   run_qull_hint_ab.bat 260810110101
rem
rem Output:
rem   drive\paul_experiments\tbn_new_systems\qull_ep_htf\ab_improve_prio_260810\
rem   drive\QULL_ImprovePriority_<stamp>.html (AB strip)
rem
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

set "STAMP=%~1"
if not defined STAMP set "STAMP=260810110101"

echo [QULL ImprovePriority AB] control stamp=%STAMP%
"%PY%" "%~dp0tools\qull_hint_ab.py" --reuse-control "%STAMP%" --stamp "%STAMP%" %2 %3 %4 %5 %6 %7 %8 %9
exit /b %ERRORLEVEL%
