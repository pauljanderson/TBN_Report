@echo off
rem RS ImprovePriority / pattern A/B on production TIME=252 baseline.
rem Control = run_rs.bat (time_stop_days=252). One knob / coherent gate per arm.
rem Docs: docs\HYPOTHESIS_TEST.md  docs\POST_RUN_ANALYSIS.md
rem
rem Usage:
rem   run_rs_post252_hint_ab.bat
rem   run_rs_post252_hint_ab.bat 260807114545
rem   set RS_SYMBOLS=APLD,BELFA & run_rs_post252_hint_ab.bat
rem
rem Output:
rem   drive\paul_experiments\rs_post252_hint_ab\<arm>\
rem   drive\paul_experiments\rs_post252_hint_ab\comparison.html
rem
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

set "STAMP=%~1"
if not defined STAMP set "STAMP=260807114545"

echo [RS post252 AB] control stamp=%STAMP%
"%PY%" "%~dp0tools\rs_post252_hint_ab.py" --reuse-control "%STAMP%" %2 %3 %4 %5 %6 %7 %8 %9
exit /b %ERRORLEVEL%
