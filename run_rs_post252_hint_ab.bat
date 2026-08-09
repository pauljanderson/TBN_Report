@echo off
rem RS ImprovePriority / pattern A/B on expanded-65 production baseline.
rem Control = run_rs.bat (stop 0.85 / target 1.25 / time_stop_days=252 / univ 65).
rem One knob / coherent gate per arm. Docs: docs\HYPOTHESIS_TEST.md  docs\POST_RUN_ANALYSIS.md
rem
rem Usage:
rem   run_rs_post252_hint_ab.bat
rem   run_rs_post252_hint_ab.bat 260807141317
rem   set RS_SYMBOLS=APG,ALBY & run_rs_post252_hint_ab.bat
rem
rem Output:
rem   drive\paul_experiments\rs_expand65_hint_ab\<arm>\
rem   drive\paul_experiments\rs_expand65_hint_ab\comparison.html
rem
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

set "STAMP=%~1"
if not defined STAMP set "STAMP=260807141317"

echo [RS expand65 AB] control stamp=%STAMP%
"%PY%" "%~dp0tools\rs_post252_hint_ab.py" --reuse-control "%STAMP%" %2 %3 %4 %5 %6 %7 %8 %9
exit /b %ERRORLEVEL%
