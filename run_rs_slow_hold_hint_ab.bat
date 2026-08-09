@echo off

rem RS slow-hold / early-TP ImprovePriority A/B on expanded-65 production baseline.

rem Control = run_rs.bat stamp 260807141317 (stop 0.85 / target 1.25 / time_stop_days=252 / univ 65).

rem Arms (one knob each; NO target expand):

rem   01 target_pct=1.15

rem   02 time_stop_days=120

rem   03 trailing_stop_increment=10   (trail-after-+10% closest RS/TBN knob)

rem   04 trailing_stop_increment=5    (winner_peak_giveback)

rem   05 sma_stop_days=20             (winner_peak_giveback alt)

rem Docs: docs\HYPOTHESIS_TEST.md  docs\TRAILING_STOPS.md  docs\POST_RUN_ANALYSIS.md

rem

rem Usage:

rem   run_rs_slow_hold_hint_ab.bat

rem   run_rs_slow_hold_hint_ab.bat 260807141317

rem   set RS_SYMBOLS=APG,ALBY & run_rs_slow_hold_hint_ab.bat

rem

rem Output:

rem   drive\paul_experiments\rs_slow_hold_hint_ab\<arm>\

rem   drive\paul_experiments\rs_slow_hold_hint_ab\comparison.html

rem

setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0"

if not defined PY call "%~dp0resolve_python.bat"

if errorlevel 1 exit /b 1



set "STAMP=%~1"

if not defined STAMP set "STAMP=260807141317"



echo [RS slow-hold AB] control stamp=%STAMP%

"%PY%" "%~dp0tools\rs_slow_hold_hint_ab.py" --reuse-control "%STAMP%" %2 %3 %4 %5 %6 %7 %8 %9

exit /b %ERRORLEVEL%

