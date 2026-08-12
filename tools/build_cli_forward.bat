@echo off
rem =============================================================================
rem Build trailing CLI forward args for run_*.bat (no setlocal — mutate caller).
rem Caller must have EnableDelayedExpansion. PY should already be resolved.
rem
rem Usage (after apply_universe_cli_arg):
rem   call "%~dp0tools\apply_universe_cli_arg.bat" XX_UNIV_ARG %1 %2
rem   call "%~dp0tools\build_cli_forward.bat" XX_FORWARD "%XX_UNIV_ARG%" %*
rem
rem CMD treats "=" and "," as argument delimiters, so unquoted:
rem   run_rl.bat -v aggressive_sell=average
rem   run_vz.bat -s NVDA,AAPL
rem arrive split; tools\build_cli_forward.py rejoins KEY=VALUE and -s lists.
rem
rem Examples:
rem   run_rl.bat -v aggressive_sell=average
rem   run_rl.bat -v "aggressive_sell=average"
rem   run_rl.bat ALL -v aggressive_sell=average
rem =============================================================================
set "_BF_OUT=%~1"
set "BUILD_CLI_FORWARD_UNIV=%~2"
set "%_BF_OUT%="
if not defined PY (
  where py >nul 2>&1 && (set "PY=py")
  if not defined PY where python >nul 2>&1 && (set "PY=python")
)
if not defined PY (
  echo ERROR: build_cli_forward.bat requires PY ^(call resolve_python.bat first^)
  exit /b 1
)
rem Skip OUTVAR + UNIV slot when building python argv (empty "" breaks cmd parsing).
set "_BF_N=0"
set "_BF_ARGS="
for %%A in (%*) do (
  set /a _BF_N+=1
  if !_BF_N! GTR 2 (
    if defined _BF_ARGS (
      set "_BF_ARGS=!_BF_ARGS! %%A"
    ) else (
      set "_BF_ARGS=%%A"
    )
  )
)
set "_BF_TMP=%TEMP%\build_cli_forward_%RANDOM%%RANDOM%.txt"
"%PY%" "%~dp0build_cli_forward.py" "%_BF_OUT%" !_BF_ARGS! >"%_BF_TMP%"
if errorlevel 1 (
  echo ERROR: build_cli_forward.py failed
  if exist "%_BF_TMP%" del "%_BF_TMP%" >nul 2>&1
  set "BUILD_CLI_FORWARD_UNIV="
  set "_BF_OUT="
  set "_BF_ARGS="
  set "_BF_TMP="
  set "_BF_N="
  exit /b 1
)
set /p _BF_LINE=<"%_BF_TMP%"
del "%_BF_TMP%" >nul 2>&1
set "%_BF_OUT%=!_BF_LINE!"
set "BUILD_CLI_FORWARD_UNIV="
set "_BF_OUT="
set "_BF_ARGS="
set "_BF_LINE="
set "_BF_TMP="
set "_BF_N="
exit /b 0
