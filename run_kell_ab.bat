@echo off
rem Kell PAC A/B stub — Wedge Pop lever arms (does NOT change run_kell.bat defaults permanently)
rem Docs: drive\paul_experiments\tbn_new_systems\kell_pac\HOW_TO_RUN.html
rem
rem Arms:
rem   00_control     — defaults (tight=0.025, trail=20, rev=0.08)
rem   01_tight_015   — kell_tight_pct=0.015
rem   02_trail_10    — kell_trail_ema=10
rem   03_rev_12      — kell_rev_ext_pct=0.12
rem
rem Universe: -s LIST | %%1 list/file | KELL_SYMBOLS | else full CSV
rem Smoke: set KELL_AB_SMOKE=1  (00_control only)
rem
rem Output copies:
rem   drive\paul_experiments\tbn_new_systems\kell_pac\ab_wedge_pop\<arm>\

setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

if not defined KELL_AGGRESSIVE set "KELL_AGGRESSIVE=true"
if not defined KELL_MAX_POSITIONS set "KELL_MAX_POSITIONS=0"

set "OUT=drive\paul_experiments\tbn_new_systems\kell_pac\ab_wedge_pop"
set "DRIVE_OUT=drive"

rem --- Universe ---
if /i "%~1"=="-s" goto :univ_from_s
if /i "%~1"=="--symbol" goto :univ_from_s
if not "%~1"=="" goto :univ_from_arg1
if defined KELL_SYMBOLS goto :univ_from_env
goto :univ_all

:univ_from_s
if "%~2"=="" (
  echo ERROR: -s requires a comma-separated symbol list
  exit /b 1
)
set "KELL_SYMBOLS=%~2"
echo [KELL AB] Universe: from -s
goto :univ_done

:univ_from_arg1
if exist "%~1" (
  set /p KELL_SYMBOLS=<"%~1"
  echo [KELL AB] Universe: from file "%~1"
) else (
  set "KELL_SYMBOLS=%~1"
  echo [KELL AB] Universe: from arg1
)
goto :univ_done

:univ_from_env
echo [KELL AB] Universe: KELL_SYMBOLS env
goto :univ_done

:univ_all
set "KELL_SYMBOLS="
echo [KELL AB] Universe: all CSV
goto :univ_done

:univ_done
set "KELL_SYM_ARGS="
if defined KELL_SYMBOLS if not "!KELL_SYMBOLS!"=="" set "KELL_SYM_ARGS=-s !KELL_SYMBOLS!"

set "KELL_AGG_FLAG="
if /i "%KELL_AGGRESSIVE%"=="true" set "KELL_AGG_FLAG=--aggressive"
if /i "%KELL_AGGRESSIVE%"=="1" set "KELL_AGG_FLAG=--aggressive"

if not exist "%OUT%" mkdir "%OUT%"

call :run_arm 00_control 0.025 20 0.08
if errorlevel 1 exit /b 1
if /i "%KELL_AB_SMOKE%"=="1" goto :done

call :run_arm 01_tight_015 0.015 20 0.08
if errorlevel 1 exit /b 1
call :run_arm 02_trail_10 0.025 10 0.08
if errorlevel 1 exit /b 1
call :run_arm 03_rev_12 0.025 20 0.12
if errorlevel 1 exit /b 1

:done
echo [KELL AB] Suite complete. Copies under %OUT%
echo [KELL AB] Summarizer: not yet ^(tools\summarize_kell_* deferred^)
exit /b 0

:run_arm
set "ARM=%~1"
set "TIGHT=%~2"
set "TRAIL=%~3"
set "REV=%~4"
set "ARM_DIR=%OUT%\%ARM%"
if not exist "!ARM_DIR!" mkdir "!ARM_DIR!"
echo.
echo [KELL AB] === arm !ARM! tight=!TIGHT! trail=!TRAIL! rev=!REV! ===
"%PY%" stock_analysis\rocket_kell_pac.py data\newdata\data -o "%DRIVE_OUT%" %KELL_AGG_FLAG% ^
  --initial-capital 500000 --aggressive-max-multiple 2.0 --margin-utilization 0.6 ^
  --max-positions %KELL_MAX_POSITIONS% ^
  --kell-exh-ban-pct 0.12 ^
  --kell-tight-pct !TIGHT! ^
  --kell-trail-ema !TRAIL! ^
  --kell-rev-ext-pct !REV! ^
  !KELL_SYM_ARGS!
if errorlevel 1 (
  echo ERROR: arm !ARM! failed
  exit /b 1
)
set /p STAMP=<"%DRIVE_OUT%\KELL_last_run_ts.txt"
if not defined STAMP (
  echo WARNING: no KELL_last_run_ts.txt — skip copy for !ARM!
  exit /b 0
)
for %%F in ("%DRIVE_OUT%\KELL_*_!STAMP!.*") do (
  copy /Y "%%~F" "!ARM_DIR!\" >nul
)
echo [KELL AB] Copied stamp !STAMP! -> !ARM_DIR!
exit /b 0
