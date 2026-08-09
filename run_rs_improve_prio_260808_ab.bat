@echo off
rem RS ImprovePriority A/B from stamp 260808222610 hints, run on gold-65 production.
rem Control = run_rs.bat (stop 0.85 / target 1.25 / time_stop_days=252 / cd=60 / univ 65).
rem Hint source: drive\RS_ImprovePriority_260808222610.html (short-hold univ report).
rem One knob / coherent gate per arm. Docs: docs\HYPOTHESIS_TEST.md
rem
rem Usage:
rem   run_rs_improve_prio_260808_ab.bat
rem   run_rs_improve_prio_260808_ab.bat 260807141317
rem
rem Output:
rem   drive\paul_experiments\rs_improve_prio_260808_ab\<arm>\
rem   drive\paul_experiments\rs_improve_prio_260808_ab\comparison.html
rem
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

set "STAMP=%~1"
if not defined STAMP set "STAMP=260807141317"

echo [RS improve_prio 260808 AB] control stamp=%STAMP%
"%PY%" "%~dp0tools\rs_improve_prio_260808_ab.py" --reuse-control "%STAMP%" %2 %3 %4 %5 %6 %7 %8 %9
exit /b %ERRORLEVEL%
