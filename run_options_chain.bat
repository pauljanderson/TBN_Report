@echo off
rem yfinance option-chain archive (dated snapshot). Archive only — not a sleeve.
rem Not gold. Not reconcile. Not LatestRun. Yahoo flake must not fail DailyRun.
rem Skip: set SKIP_OPTIONS_CHAIN=1
rem Standalone: run_options_chain.bat
rem Widen later: run_options_chain.bat --symbols NVDA,AAPL   or edit data\options\options_universe.csv
setlocal EnableExtensions
cd /d "%~dp0"

if /i "%SKIP_OPTIONS_CHAIN%"=="1" (
  echo [options-chain] SKIPPED - SKIP_OPTIONS_CHAIN=1
  exit /b 0
)

set "PY="
if defined PYTHON_EXE set "PY=%PYTHON_EXE%"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
if not defined PY set "PY=python"

echo [options-chain] save_option_chain_daily --soft-fail
"%PY%" "%~dp0tools\save_option_chain_daily.py" --soft-fail %*
if errorlevel 1 (
  echo [options-chain] WARN - saver returned %errorlevel%; treating as warning so DailyRun continues
)

rem Always 0: archive must not break stock DailyRun.
exit /b 0
