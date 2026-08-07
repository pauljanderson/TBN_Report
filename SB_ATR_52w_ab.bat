@echo off
rem StockBee Momentum Burst — ATR%% + DIST_TO_52W_HIGH A/B (root alias)
rem Canonical suite + EDITABLE SETTINGS: run_sb_ab_atr_52w.bat
rem   Open that file → change ATR_MIN / DIST52_MIN near top → save → run this alias.
rem Docs: drive\paul_experiments\tbn_new_systems\stockbee_momentum_burst\HOW_TO_RUN.html
rem
rem Usage:
rem   SB_ATR_52w_ab.bat
rem   SB_ATR_52w_ab.bat HROW,REAL,AKR
rem   SB_ATR_52w_ab.bat -s HROW,REAL,AKR
rem   SB_ATR_52w_ab.bat -s "HROW,REAL,AKR"
rem   SB_ATR_52w_ab.bat drive\paul_experiments\tbn_new_systems\stockbee_momentum_burst\GOLD_UNIVERSE.csv
rem   set SB_ATR_SMOKE=1 && SB_ATR_52w_ab.bat -s HROW,REAL,AKR
rem
rem Arms: control / atr-only(ATR_MIN) / dist52-only(DIST52_MIN) / both
rem   (thresholds live in run_sb_ab_atr_52w.bat "EDIT DEFAULTS HERE" block)

echo.
echo === SB ATR / 52w-high A/B ===
echo Usage:
echo   SB_ATR_52w_ab.bat
echo   SB_ATR_52w_ab.bat HROW,REAL,AKR
echo   SB_ATR_52w_ab.bat -s HROW,REAL,AKR
echo   SB_ATR_52w_ab.bat -s "HROW,REAL,AKR"
echo   SB_ATR_52w_ab.bat path\to\universe.csv
echo   set SB_ATR_SMOKE=1 ^&^& SB_ATR_52w_ab.bat -s HROW,REAL,AKR
echo Default universe: GOLD_UNIVERSE.csv when %%1 and SB_SYMBOLS unset.
echo EDIT gates: open run_sb_ab_atr_52w.bat — ATR_MIN / DIST52_MIN at top ^(EDIT DEFAULTS HERE^)
echo.

setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

rem Resolve universe here and export SB_SYMBOLS so comma lists never depend on %%* re-parse.
if /i "%~1"=="-s" goto :alias_from_s
if /i "%~1"=="--symbol" goto :alias_from_s
if not "%~1"=="" goto :alias_from_arg1
call "%~dp0run_sb_ab_atr_52w.bat"
exit /b %errorlevel%

:alias_from_s
if "%~2"=="" (
  echo ERROR: %~1 requires a symbol list
  echo Example: SB_ATR_52w_ab.bat -s HROW,REAL,AKR
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
  call "%~dp0run_sb_ab_atr_52w.bat" "%~1"
  exit /b %errorlevel%
)
if exist "%~dp0%~1" (
  call "%~dp0run_sb_ab_atr_52w.bat" "%~dp0%~1"
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
rem Child picks up SB_SYMBOLS from environment (no fragile %%1/-s forward).
call "%~dp0run_sb_ab_atr_52w.bat"
exit /b %errorlevel%
