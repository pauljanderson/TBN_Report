@echo off
rem CAN SLIM A/B stub: sweep RS / pivot lookback / volume breakout mult
rem Does NOT change run_canslim.bat production defaults permanently.
rem
rem Arms:
rem   00_control       ? rs=80 pivot=55 vol=1.40
rem   01_rs70          ? rs_min=70
rem   02_rs90          ? rs_min=90
rem   03_pivot40       ? pivot_lookback=40
rem   04_pivot70       ? pivot_lookback=70
rem   05_vol120        ? vol_breakout_mult=1.20
rem   06_vol180        ? vol_breakout_mult=1.80
rem
rem Universe: -s LIST | %%1 list/file | CS_SYMBOLS | else small smoke list
rem Output copies: drive\paul_experiments\tbn_new_systems\oneil_canslim\ab_rs_pivot_vol\<arm>\
rem Smoke one arm: set CS_AB_SMOKE=1
rem
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

set "OUT=drive\paul_experiments\tbn_new_systems\oneil_canslim\ab_rs_pivot_vol"
set "DRIVE_OUT=drive"
if not defined CS_WORKERS set "CS_WORKERS=0"
if not defined CS_AGGRESSIVE set "CS_AGGRESSIVE=true"
if not defined CS_MARKET_GATE set "CS_MARKET_GATE=true"

rem --- Universe ---
set "CS_UNIVERSE_SRC="
if /i "%~1"=="-s" goto :univ_s
if /i "%~1"=="--symbol" goto :univ_s
if not "%~1"=="" goto :univ_arg1
if defined CS_SYMBOLS goto :univ_env
set "CS_SYMBOLS=NVDA,TSLA,AMD,META,AMZN,AVGO,CRM,CRWD,NET,PLTR"
set "CS_UNIVERSE_SRC=smoke_default"
echo [CS AB] Universe: smoke default (!CS_SYMBOLS!)
goto :univ_done

:univ_s
if "%~2"=="" (
  echo ERROR: -s requires a symbol list
  exit /b 1
)
set "CS_SYMBOLS=%~2"
set "CS_UNIVERSE_SRC=-s"
echo [CS AB] Universe: from -s
goto :univ_done

:univ_arg1
if exist "%~1" (
  set /p CS_SYMBOLS=<"%~1"
  set "CS_UNIVERSE_SRC=file:%~1"
  echo [CS AB] Universe: from file "%~1"
  goto :univ_done
)
set "CS_SYMBOLS=%~1"
set "CS_UNIVERSE_SRC=%%1"
echo [CS AB] Universe: from %%1
goto :univ_done

:univ_env
set "CS_UNIVERSE_SRC=env"
echo [CS AB] Universe: from CS_SYMBOLS env

:univ_done
mkdir "%OUT%" 2>nul
echo [CS AB] Out root: %OUT%
echo [CS AB] Market gate: %CS_MARKET_GATE%

set "ARMS=00_control 01_rs70 02_rs90 03_pivot40 04_pivot70 05_vol120 06_vol180"
if /i "%CS_AB_SMOKE%"=="1" set "ARMS=00_control"

for %%A in (%ARMS%) do (
  echo.
  echo ========== ARM %%A ==========
  set "RS=80"
  set "PIV=55"
  set "VOL=1.40"
  if /i "%%A"=="01_rs70" set "RS=70"
  if /i "%%A"=="02_rs90" set "RS=90"
  if /i "%%A"=="03_pivot40" set "PIV=40"
  if /i "%%A"=="04_pivot70" set "PIV=70"
  if /i "%%A"=="05_vol120" set "VOL=1.20"
  if /i "%%A"=="06_vol180" set "VOL=1.80"

  set "CS_RS_MIN=!RS!"
  set "CS_PIVOT_LB=!PIV!"
  set "CS_VOL_MULT=!VOL!"
  set "CS_SYMBOLS=%CS_SYMBOLS%"
  call "%~dp0run_canslim.bat"
  if errorlevel 1 (
    echo [CS AB] ARM %%A FAILED
    exit /b 1
  )
  set "ARM_DIR=%OUT%\%%A"
  mkdir "!ARM_DIR!" 2>nul
  if exist "drive\CS_last_run_ts.txt" (
    set /p STAMP=<"drive\CS_last_run_ts.txt"
    for %%F in (Closed Open Summary Watchlist Audit_Report EquityCurve EquityMeta Report) do (
      if exist "drive\CS_%%F_!STAMP!.csv" copy /Y "drive\CS_%%F_!STAMP!.csv" "!ARM_DIR!\" >nul
      if exist "drive\CS_%%F_!STAMP!.txt" copy /Y "drive\CS_%%F_!STAMP!.txt" "!ARM_DIR!\" >nul
    )
    echo !STAMP!> "!ARM_DIR!\stamp.txt"
    echo [CS AB] Copied stamp !STAMP! ? !ARM_DIR!
  )
)

echo.
echo [CS AB] Done. Compare under %OUT%
exit /b 0
