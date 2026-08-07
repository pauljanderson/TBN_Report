@echo off
rem =============================================================================
rem Parse leading universe CLI for run_*.bat (no setlocal — mutate caller).
rem Usage:
rem   call "%~dp0tools\apply_universe_cli_arg.bat" OUTVAR %1 %2
rem Sets OUTVAR to:
rem   ALL / * / --all  → full-universe token for load_universe_csv.bat
rem   full path        → when arg1 is a .csv override
rem   empty            → use default / env load order
rem Also accepts -s * | -s ALL | -s --all (legacy mistaken UX).
rem Prefer: run_rs.bat ALL  (PowerShell expands bare *; quote "*" if needed)
rem =============================================================================
set "_AU_OUT=%~1"
if "%_AU_OUT%"=="" (
  echo ERROR: apply_universe_cli_arg.bat requires OUTVAR name
  exit /b 1
)
set "%_AU_OUT%="
set "_AU_A=%~2"
set "_AU_B=%~3"
if /i "%_AU_A%"=="*" set "%_AU_OUT%=*"
if /i "%_AU_A%"=="ALL" set "%_AU_OUT%=ALL"
if /i "%_AU_A%"=="--all" set "%_AU_OUT%=--all"
if /i "%~x2"==".csv" set "%_AU_OUT%=%~f2"
if /i "%_AU_A%"=="-s" (
  if /i "%_AU_B%"=="*" set "%_AU_OUT%=*"
  if /i "%_AU_B%"=="ALL" set "%_AU_OUT%=ALL"
  if /i "%_AU_B%"=="--all" set "%_AU_OUT%=--all"
)
set "_AU_OUT="
set "_AU_A="
set "_AU_B="
exit /b 0
