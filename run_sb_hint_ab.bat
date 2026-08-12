@echo off
rem SB ImprovePriority / ImproveHints A/B on gold-56 production baseline.
rem Control = run_sb.bat (target 1.097 / burst_max_risk 0.078 / time_stop=5).
rem One knob / coherent skip per arm. Docs: docs\HYPOTHESIS_TEST.md
rem
rem Usage:
rem   run_sb_hint_ab.bat
rem   run_sb_hint_ab.bat 260807184031
rem   set SB_SYMBOLS=HROW,AKR & run_sb_hint_ab.bat
rem
rem Output:
rem   drive\paul_experiments\tbn_new_systems\stockbee_momentum_burst\ab_improve_hints\
rem   drive\SB_ImprovePriority_<stamp>.html (generated + AB strip)
rem
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

set "STAMP=%~1"
if not defined STAMP set "STAMP=260807184031"

echo [SB ImproveHints AB] control stamp=%STAMP%
"%PY%" "%~dp0tools\sb_hint_ab.py" --reuse-control "%STAMP%" --stamp "%STAMP%" %2 %3 %4 %5 %6 %7 %8 %9
exit /b %ERRORLEVEL%
