@echo off
rem Qull HTF A/B: prior_run_pct sweep (qull_prior_run_pct)
rem Does NOT change production run_qull.bat defaults.
rem
rem EDIT DEFAULTS HERE — save, then run.
rem
rem Arms:
rem   00_control     — prior_run=PRIOR_CTRL (default 0.50)
rem   01_prior_0_30  — 0.30
rem   02_prior_0_50  — 0.50 (dup control for parity check)
rem   03_prior_0_80  — 0.80
rem   04_prior_1_00  — 1.00
rem
rem Universe: -s LIST | %%1 | QULL_SYMBOLS | else SEED_UNIVERSE.csv
rem Output copies: drive\paul_experiments\tbn_new_systems\qull_ep_htf\ab_prior_run\<arm>\
rem After suite: tools\summarize_qull_prior_run_ab.py

setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

rem === EDIT DEFAULTS HERE ===
if not defined PRIOR_CTRL set "PRIOR_CTRL=0.50"
if not defined PRIOR_0_30 set "PRIOR_0_30=0.30"
if not defined PRIOR_0_50 set "PRIOR_0_50=0.50"
if not defined PRIOR_0_80 set "PRIOR_0_80=0.80"
if not defined PRIOR_1_00 set "PRIOR_1_00=1.00"
if not defined RUN_WORKERS set "RUN_WORKERS=8"
if not defined RUN_AGGRESSIVE set "RUN_AGGRESSIVE=true"
if not defined QULL_AB_SMOKE set "QULL_AB_SMOKE=0"
rem === END EDIT DEFAULTS ===

set "DOCROOT=drive\paul_experiments\tbn_new_systems\qull_ep_htf"
set "ABROOT=%DOCROOT%\ab_prior_run"
set "SEEDCSV=%DOCROOT%\SEED_UNIVERSE.csv"

rem Parse -s / first arg
set "SYM_LIST="
if /i "%~1"=="-s" (
  set "SYM_LIST=%~2"
  shift
  shift
) else if /i "%~1"=="--symbol" (
  set "SYM_LIST=%~2"
  shift
  shift
) else if not "%~1"=="" (
  set "SYM_LIST=%~1"
  shift
)
if not defined SYM_LIST if defined QULL_SYMBOLS set "SYM_LIST=%QULL_SYMBOLS%"
if not defined SYM_LIST if exist "%SEEDCSV%" (
  set /p SYM_LIST=<"%SEEDCSV%"
)
if not defined SYM_LIST (
  echo [QULL-AB] No universe — set QULL_SYMBOLS or pass -s LIST
  exit /b 2
)

set "AGG_FLAG="
if /i "%RUN_AGGRESSIVE%"=="true" set "AGG_FLAG=--aggressive"

echo [QULL-AB] prior_run sweep universe=%SYM_LIST%
echo [QULL-AB] control=%PRIOR_CTRL% arms=0.30/0.50/0.80/1.00 smoke=%QULL_AB_SMOKE%

call :run_arm 00_control %PRIOR_CTRL%
if errorlevel 1 exit /b %errorlevel%
if "%QULL_AB_SMOKE%"=="1" goto :summarize

call :run_arm 01_prior_0_30 %PRIOR_0_30%
if errorlevel 1 exit /b %errorlevel%
call :run_arm 02_prior_0_50 %PRIOR_0_50%
if errorlevel 1 exit /b %errorlevel%
call :run_arm 03_prior_0_80 %PRIOR_0_80%
if errorlevel 1 exit /b %errorlevel%
call :run_arm 04_prior_1_00 %PRIOR_1_00%
if errorlevel 1 exit /b %errorlevel%

:summarize
"%PY%" tools\summarize_qull_prior_run_ab.py --ab-root "%ABROOT%"
if errorlevel 1 (
  echo [QULL-AB] summarize failed
  exit /b %errorlevel%
)
echo [QULL-AB] Done. See %ABROOT%\comparison.html
exit /b 0

:run_arm
set "ARM=%~1"
set "PRIOR=%~2"
set "ARMDIR=%ABROOT%\%ARM%"
if not exist "%ARMDIR%" mkdir "%ARMDIR%"
echo.
echo ========== ARM %ARM% prior_run_pct=%PRIOR% ==========
set "QULL_SETUP=htf"
set "QULL_PRIOR_RUN=%PRIOR%"
set "QULL_SYMBOLS=%SYM_LIST%"
set "QULL_WORKERS=%RUN_WORKERS%"
set "QULL_AGGRESSIVE=%RUN_AGGRESSIVE%"
call "%~dp0run_qullamaggie_htf.bat" --no-yfinance
if errorlevel 1 (
  echo [QULL-AB] ARM %ARM% FAILED
  exit /b 1
)
if not exist "drive\QULL_last_run_ts.txt" (
  echo [QULL-AB] missing QULL_last_run_ts.txt
  exit /b 1
)
set /p STAMP=<drive\QULL_last_run_ts.txt
echo [QULL-AB] stamp=%STAMP% → %ARMDIR%
for %%F in (
  QULL_Closed_%STAMP%.csv
  QULL_Summary_%STAMP%.csv
  QULL_Audit_Report_%STAMP%.csv
  QULL_Report_%STAMP%.csv
  QULL_Open_%STAMP%.csv
) do (
  if exist "drive\%%F" copy /Y "drive\%%F" "%ARMDIR%\%%F" >nul
)
echo %STAMP%> "%ARMDIR%\stamp.txt"
echo prior_run_pct=%PRIOR%> "%ARMDIR%\arm_meta.txt"
exit /b 0
