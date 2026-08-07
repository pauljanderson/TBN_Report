@echo off
rem StockBee Momentum Burst — Market Monitor + 2Lynch T-1 N A/B (root alias)
rem Canonical suite + EDITABLE SETTINGS: run_sb_ab_mm_2lynch.bat
rem   Open that file → change MM_RATIO_* / RUN_* near top → save → run this alias.
rem Spec: drive\paul_experiments\tbn_new_systems\stockbee_momentum_burst\SB_NEXT_BUILDS.html
rem
rem Usage:
rem   SB_MM_2Lynch_ab.bat
rem   SB_MM_2Lynch_ab.bat HROW,REAL,AKR
rem   SB_MM_2Lynch_ab.bat -s HROW,REAL,AKR
rem   SB_MM_2Lynch_ab.bat -s "HROW,REAL,AKR"
rem   SB_MM_2Lynch_ab.bat drive\paul_experiments\tbn_new_systems\stockbee_momentum_burst\GOLD_UNIVERSE.csv
rem   set SB_MM_SMOKE=1 && SB_MM_2Lynch_ab.bat -s HROW,REAL,AKR
rem
rem Arms: control / mm soft|default|tight / t1_n / mm+t1 combos

echo.
echo === SB Market Monitor / 2Lynch T-1 N A/B ===
echo Usage:
echo   SB_MM_2Lynch_ab.bat
echo   SB_MM_2Lynch_ab.bat HROW,REAL,AKR
echo   SB_MM_2Lynch_ab.bat -s HROW,REAL,AKR
echo   SB_MM_2Lynch_ab.bat -s "HROW,REAL,AKR"
echo   SB_MM_2Lynch_ab.bat path\to\universe.csv
echo   set SB_MM_SMOKE=1 ^&^& SB_MM_2Lynch_ab.bat -s HROW,REAL,AKR
echo Default universe: GOLD_UNIVERSE.csv when %%1 and SB_SYMBOLS unset.
echo EDIT gates: open run_sb_ab_mm_2lynch.bat — MM_RATIO_* / RUN_* at top ^(EDIT DEFAULTS HERE^)
echo.

setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

if /i "%~1"=="-s" goto :alias_from_s
if /i "%~1"=="--symbol" goto :alias_from_s
if not "%~1"=="" goto :alias_from_arg1
call "%~dp0run_sb_ab_mm_2lynch.bat"
exit /b %errorlevel%

:alias_from_s
if "%~2"=="" (
  echo ERROR: %~1 requires a symbol list
  echo Example: SB_MM_2Lynch_ab.bat -s HROW,REAL,AKR
  exit /b 1
)
set "SB_SYMBOLS=%~2"
shift
shift
:alias_join_s
if "%~1"=="" goto :alias_run_env
set "SB_JOIN_TOK=%~1"
if "!SB_JOIN_TOK:~0,1!"=="-" goto :alias_run_env
set "SB_SYMBOLS=!SB_SYMBOLS!,!SB_JOIN_TOK!"
shift
goto :alias_join_s

:alias_from_arg1
if exist "%~1" (
  call "%~dp0run_sb_ab_mm_2lynch.bat" "%~1"
  exit /b %errorlevel%
)
if exist "%~dp0%~1" (
  call "%~dp0run_sb_ab_mm_2lynch.bat" "%~dp0%~1"
  exit /b %errorlevel%
)
set "SB_SYMBOLS=%~1"
shift
:alias_join_a
if "%~1"=="" goto :alias_run_env
set "SB_JOIN_TOK=%~1"
if "!SB_JOIN_TOK:~0,1!"=="-" goto :alias_run_env
set "SB_SYMBOLS=!SB_SYMBOLS!,!SB_JOIN_TOK!"
shift
goto :alias_join_a

:alias_run_env
call "%~dp0run_sb_ab_mm_2lynch.bat"
exit /b %errorlevel%
