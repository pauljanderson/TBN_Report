@echo off
rem YH ImprovePriority param-hint A/B (band / target / stop)
rem Hypothesis test: one knob per arm vs frozen run_yh.bat control.
rem Docs: docs\HYPOTHESIS_TEST.md  docs\POST_RUN_ANALYSIS.md
rem
rem Usage:
rem   run_yh_param_hint_ab.bat
rem   run_yh_param_hint_ab.bat 260807080037
rem   run_yh_param_hint_ab.bat --stamp 260807080037 --reuse-control
rem   set YH_PARAM_AB_SMOKE=1 & run_yh_param_hint_ab.bat
rem
rem Output:
rem   drive\paul_experiments\yh_param_hint_ab\<arm>\
rem   drive\paul_experiments\yh_param_hint_ab\comparison.html
rem
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

set "EXTRA="
if /i "%YH_PARAM_AB_SMOKE%"=="1" set "EXTRA=!EXTRA! --smoke"
if /i "%YH_PARAM_AB_SMOKE%"=="true" set "EXTRA=!EXTRA! --smoke"

if "%~1"=="" (
  echo [YH param AB] No stamp — resolving latest ImproveHints / last_run_ts
  "%PY%" "%~dp0tools\yh_param_hint_ab.py" --reuse-control !EXTRA!
  exit /b !ERRORLEVEL!
)

rem Flags pass through; bare stamp gets --stamp + --reuse-control
echo %~1| findstr /b /c:"-" >nul
if not errorlevel 1 (
  "%PY%" "%~dp0tools\yh_param_hint_ab.py" --reuse-control !EXTRA! %*
  exit /b !ERRORLEVEL!
)

"%PY%" "%~dp0tools\yh_param_hint_ab.py" --stamp "%~1" --reuse-control !EXTRA! %2 %3 %4 %5 %6 %7 %8 %9
exit /b %ERRORLEVEL%
