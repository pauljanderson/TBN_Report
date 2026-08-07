@echo off
rem Qull EP/HTF A/B stub — prior_run / coil_range / trail_ema arms
rem Does NOT change production (there is no DailyRun QULL yet).
rem Spec: drive\paul_experiments\tbn_new_systems\qull_ep_htf\RESEARCH.md §F
rem Docs: drive\paul_experiments\tbn_new_systems\qull_ep_htf\DNA.md
rem
rem Arms:
rem   00_control       — defaults (prior=0.50, coil_range=0.15, trail=10)
rem   01_prior_0_30    — prior_run=0.30
rem   02_prior_0_80    — prior_run=0.80
rem   03_prior_1_00    — prior_run=1.00
rem   04_coil_0_10     — coil_range=0.10
rem   05_coil_0_20     — coil_range=0.20
rem   06_trail_20      — trail_ema=20
rem
rem   set QULL_AB_SMOKE=1  → 00_control only
rem   set QULL_AB_RESOLVE_ONLY=1 → echo arms, no runs
rem
rem Output copies under:
rem   drive\paul_experiments\tbn_new_systems\qull_ep_htf\ab_prior_run\<arm>\
rem   drive\paul_experiments\tbn_new_systems\qull_ep_htf\ab_coil_range\<arm>\
rem   drive\paul_experiments\tbn_new_systems\qull_ep_htf\ab_trail_ema\<arm>\

setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

set "QULL_AB_ROOT=%~dp0drive\paul_experiments\tbn_new_systems\qull_ep_htf"
set "QULL_SEED=TSLA,NVDA,AMD,NET,SNOW,CRWD,SHOP,ROKU,DKNG,PLTR,SMCI,ARM,HOOD,MSTR"

rem --- optional -s / positional symbols ---
if /i "%~1"=="-s" (
  set "QULL_SYMBOLS=%~2"
  shift
  shift
) else if /i "%~1"=="--symbol" (
  set "QULL_SYMBOLS=%~2"
  shift
  shift
) else if not "%~1"=="" (
  set "QULL_SYMBOLS=%~1"
  shift
)
if not defined QULL_SYMBOLS set "QULL_SYMBOLS=%QULL_SEED%"

if /i "%QULL_AB_RESOLVE_ONLY%"=="1" (
  echo [QULL-AB] symbols=!QULL_SYMBOLS!
  echo [QULL-AB] arms: 00_control 01_prior_0_30 02_prior_0_80 03_prior_1_00 04_coil_0_10 05_coil_0_20 06_trail_20
  exit /b 0
)

call :run_arm 00_control     prior ab_prior_run 0.50 0.15 10
if errorlevel 1 exit /b 1
if /i "%QULL_AB_SMOKE%"=="1" goto :done

call :run_arm 01_prior_0_30  prior ab_prior_run 0.30 0.15 10
call :run_arm 02_prior_0_80  prior ab_prior_run 0.80 0.15 10
call :run_arm 03_prior_1_00  prior ab_prior_run 1.00 0.15 10
call :run_arm 04_coil_0_10   coil  ab_coil_range 0.50 0.10 10
call :run_arm 05_coil_0_20   coil  ab_coil_range 0.50 0.20 10
call :run_arm 06_trail_20    trail ab_trail_ema 0.50 0.15 20

:done
echo [QULL-AB] complete
exit /b 0

:run_arm
set "ARM=%~1"
set "FAMILY=%~2"
set "SUBDIR=%~3"
set "PRIOR=%~4"
set "COILR=%~5"
set "TRAIL=%~6"
set "DEST=%QULL_AB_ROOT%\%SUBDIR%\%ARM%"
if not exist "%DEST%" mkdir "%DEST%"
echo.
echo [QULL-AB] === %ARM% prior=%PRIOR% coil_range=%COILR% trail=%TRAIL% ===
set "QULL_PRIOR_RUN=%PRIOR%"
set "QULL_COIL_RANGE=%COILR%"
set "QULL_TRAIL_EMA=%TRAIL%"
call "%~dp0run_qull_standalone.bat"
if errorlevel 1 (
  echo [QULL-AB] FAILED arm %ARM%
  exit /b 1
)
rem Copy latest stamp artifacts into arm folder
set "TSFILE=%~dp0drive\QULL_last_run_ts.txt"
if not exist "%TSFILE%" (
  echo [QULL-AB] WARN: no QULL_last_run_ts.txt after %ARM%
  exit /b 0
)
set /p TS=<"%TSFILE%"
for %%F in (
  QULL_Closed_%TS%.csv
  QULL_Open_%TS%.csv
  QULL_Summary_%TS%.csv
  QULL_Watchlist_%TS%.csv
  QULL_Report_%TS%.txt
  QULL_Audit_Report_%TS%.csv
  QULL_EquityCurve_%TS%.csv
) do (
  if exist "%~dp0drive\%%F" copy /Y "%~dp0drive\%%F" "%DEST%\%%F" >nul
)
echo %TS%>"%DEST%\stamp.txt"
echo [QULL-AB] copied stamp %TS% -> %DEST%
exit /b 0
