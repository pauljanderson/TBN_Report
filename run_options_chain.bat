@echo off
rem Standalone options-chain archive. Not a DailyRun step (removed 2026-10-02).
rem yfinance dated snapshot of the warehouse in data\options\options_universe.csv.
rem Archive only — not a sleeve, not gold, not reconcile, not LatestRun.
rem Optional skip: set SKIP_OPTIONS_CHAIN=1
rem Narrow a run: run_options_chain.bat --symbols NVDA,AAPL
setlocal EnableExtensions
cd /d "%~dp0"

echo ============================================================
echo Options chain archive (standalone — not part of DailyRun)
echo Warehouse list: data\options\options_universe.csv
echo First 6 expiries. Same calendar day overwrites. A Yahoo miss exits 0.
echo ============================================================

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
  echo [options-chain] WARN - saver returned %errorlevel%; treating as a warning, not a crash
)

rem Always 0: a Yahoo miss must not look like a crash.
exit /b 0
