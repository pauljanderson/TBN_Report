@echo off
rem Run all three YH taken-trade pattern A/Bs (Mag9 w/o TSLA), then refresh deep analysis HTML.
rem   run_yh_ab_patterns.bat
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

set "FAIL=0"
call "%~dp0run_yh_ab_false_start.bat"
if errorlevel 1 set /a FAIL+=1
call "%~dp0run_yh_ab_post_target.bat"
if errorlevel 1 set /a FAIL+=1
call "%~dp0run_yh_ab_fat_stops.bat"
if errorlevel 1 set /a FAIL+=1

echo.
echo === Building YH_Deep_Analysis.html ===
"%PY%" "%~dp0tools\build_yh_deep_analysis.py"
if errorlevel 1 set /a FAIL+=1

if !FAIL! gtr 0 (
  echo DONE with !FAIL! suite failure(s)
  exit /b 1
)
echo DONE all YH pattern A/Bs + deep analysis
exit /b 0
