@echo off
rem =============================================================================
rem Shared universe loader for run_*.bat
rem Usage (from repo root):
rem   call "%~dp0tools\load_universe_csv.bat" SYS [optional_override_csv|ALL|*|--all]
rem
rem SYS = BRT | YH | WPBR | RS | RL | MTS | IND | SB | MVCP | QULL | KELL | CS | VEC | VZ
rem
rem Load order:
rem   0. If arg2 is * / ALL / --all → full scan (CLI; beats ambient %%SYS%%_SYMBOLS)
rem   1. If %%SYS%%_SYMBOLS already set and non-empty → keep it
rem   2. Else if %%SYS%%_ALL_CSV is 1/true/yes → set SYMBOLS=*
rem   3. Else if arg2 or %%SYS%%_UNIVERSE_CSV set → load that CSV
rem   4. Else load drive\universes\%%SYS%%_universe.csv
rem
rem CSV: one ticker per line (# / blanks ignored). missing / empty → *
rem   Sole-token * or ALL → * (full scan). ALL among other rows = Allstate ticker.
rem Legacy single-line comma lists OK (via Python helper).
rem
rem Sets in caller env:
rem   %%SYS%%_SYMBOLS       comma list or *
rem   %%SYS%%_PASS_SYMBOLS  1 = pass -s; 0 = omit -s (full scan)
rem   %%SYS%%_UNIVERSE_SRC  cli_all | env | all_csv | override | default | missing
rem =============================================================================

rem No setlocal: mutate caller env directly (required for dynamic %%SYS%%_* names).
set "_LU_SYS=%~1"
set "_LU_ARG=%~2"
if "%_LU_SYS%"=="" (
  echo ERROR: load_universe_csv.bat requires SYS prefix e.g. BRT
  exit /b 1
)

set "_LU_ROOT=%~dp0.."
for %%I in ("%_LU_ROOT%") do set "_LU_ROOT=%%~fI"

call set "_LU_CUR=%%%_LU_SYS%_SYMBOLS%%"
call set "_LU_ENV_CSV=%%%_LU_SYS%_UNIVERSE_CSV%%"
call set "_LU_ALL=%%%_LU_SYS%_ALL_CSV%%"

if defined _LU_ALL set "_LU_ALL=%_LU_ALL: =%"

rem Trim trailing spaces on SYMBOLS (* && quirk) — needs delayed expansion
setlocal EnableDelayedExpansion
if not defined _LU_CUR goto _lu_trim_skip
set "_T=!_LU_CUR!"
:_lu_trim
if "!_T!"=="" goto _lu_trim_done
if not "!_T:~-1!"==" " goto _lu_trim_done
set "_T=!_T:~0,-1!"
goto _lu_trim
:_lu_trim_done
endlocal & set "_LU_CUR=%_T%"
goto _lu_trim_end
:_lu_trim_skip
endlocal
:_lu_trim_end

set "_LU_SRC="
set "_LU_VAL="

rem 0) Explicit CLI full-universe tokens (run_*.bat ALL) — prefer over ambient env
if /i "%_LU_ARG%"=="*" goto _lu_cli_all
if /i "%_LU_ARG%"=="ALL" goto _lu_cli_all
if /i "%_LU_ARG%"=="--all" goto _lu_cli_all
goto _lu_after_cli_all
:_lu_cli_all
set "_LU_VAL=*"
set "_LU_SRC=cli_all"
goto _lu_finalize
:_lu_after_cli_all

rem 1) Already set?
if defined _LU_CUR if not "%_LU_CUR%"=="" (
  set "_LU_VAL=%_LU_CUR%"
  set "_LU_SRC=env"
  goto _lu_finalize
)

rem 2) System ALL flag
if /i "%_LU_ALL%"=="1" set "_LU_VAL=*"
if /i "%_LU_ALL%"=="true" set "_LU_VAL=*"
if /i "%_LU_ALL%"=="yes" set "_LU_VAL=*"
if defined _LU_VAL (
  set "_LU_SRC=all_csv"
  goto _lu_finalize
)

rem 3) Override CSV
set "_LU_FILE="
if defined _LU_ARG if not "%_LU_ARG%"=="" set "_LU_FILE=%_LU_ARG%"
if not defined _LU_FILE if defined _LU_ENV_CSV if not "%_LU_ENV_CSV%"=="" set "_LU_FILE=%_LU_ENV_CSV%"
if defined _LU_FILE (
  set "_LU_SRC=override"
  goto _lu_load_file
)

rem 4) Default
set "_LU_FILE=%_LU_ROOT%\drive\universes\%_LU_SYS%_universe.csv"
set "_LU_SRC=default"

:_lu_load_file
set "_LU_OUT=%TEMP%\lu_%_LU_SYS%_%RANDOM%%RANDOM%.txt"
set "_LU_PYCMD="
if defined PY set "_LU_PYCMD=%PY%"
if not defined _LU_PYCMD where py >nul 2>&1 && set "_LU_PYCMD=py -3"
if not defined _LU_PYCMD where python >nul 2>&1 && set "_LU_PYCMD=python"

if defined _LU_PYCMD (
  %_LU_PYCMD% "%_LU_ROOT%\tools\load_universe_csv.py" "%_LU_FILE%" --out "%_LU_OUT%" 2>nul
  if not errorlevel 1 if exist "%_LU_OUT%" (
    rem set /p truncates at 1023 chars — use for /f for expanded universes
    for /f "usebackq delims=" %%A in ("%_LU_OUT%") do set "_LU_VAL=%%A"
    del "%_LU_OUT%" >nul 2>&1
    goto _lu_finalize
  )
)

rem Bat fallback (one ticker per line; legacy comma-on-one-line kept as-is via set /p first line if commas)
if exist "%_LU_OUT%" del "%_LU_OUT%" >nul 2>&1
if not exist "%_LU_FILE%" (
  set "_LU_VAL=*"
  set "_LU_SRC=missing"
  goto _lu_finalize
)
setlocal EnableDelayedExpansion
set "_LU_VAL="
set "_LU_STOP="
for /f "usebackq eol=# tokens=* delims=" %%L in ("%_LU_FILE%") do (
  if not defined _LU_STOP (
    set "_LINE=%%L"
    for /f "tokens=1 delims=#" %%T in ("!_LINE!") do set "_LINE=%%T"
    rem trim spaces
    for /f "tokens=* delims= " %%T in ("!_LINE!") do set "_LINE=%%T"
    if not "!_LINE!"=="" (
      if "!_LINE:,=!" NEQ "!_LINE!" (
        rem Legacy one-liner with commas (may include ALL ticker)
        set "_LU_VAL=!_LINE!"
        set "_LU_STOP=1"
      ) else if /i "!_LINE!"=="*" (
        rem collect; sole * handled after loop / finalize
        if defined _LU_VAL (
          rem bare * mixed with tickers — skip
        ) else (
          set "_LU_VAL=*"
        )
      ) else if defined _LU_VAL (
        if /i "!_LU_VAL!"=="*" (
          rem prior sole * was provisional; real ticker wins — start list
          set "_LU_VAL=!_LINE!"
        ) else (
          set "_LU_VAL=!_LU_VAL!,!_LINE!"
        )
      ) else (
        set "_LU_VAL=!_LINE!"
      )
    )
  )
)
if not defined _LU_VAL set "_LU_VAL=*"
rem Sole ALL → full scan (legacy); ALL in a comma list stays as Allstate
if /i "!_LU_VAL!"=="ALL" set "_LU_VAL=*"
endlocal & set "_LU_VAL=%_LU_VAL%"

:_lu_finalize
if not defined _LU_VAL set "_LU_VAL=*"
set "_LU_PASS=1"
if /i "%_LU_VAL%"=="*" set "_LU_PASS=0"
if /i "%_LU_VAL%"=="ALL" (
  set "_LU_VAL=*"
  set "_LU_PASS=0"
)
if "%_LU_VAL%"=="" (
  set "_LU_VAL=*"
  set "_LU_PASS=0"
)

rem Export to %%SYS%%_* in caller env
set "%_LU_SYS%_SYMBOLS=%_LU_VAL%"
set "%_LU_SYS%_PASS_SYMBOLS=%_LU_PASS%"
set "%_LU_SYS%_UNIVERSE_SRC=%_LU_SRC%"

rem Cleanup temps
set "_LU_SYS="
set "_LU_ARG="
set "_LU_ROOT="
set "_LU_CUR="
set "_LU_ENV_CSV="
set "_LU_ALL="
set "_LU_SRC="
set "_LU_VAL="
set "_LU_FILE="
set "_LU_OUT="
set "_LU_PYCMD="
set "_LU_PASS="
exit /b 0
