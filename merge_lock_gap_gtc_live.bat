@echo off
rem =============================================================================
rem merge_lock_gap_gtc_live.bat
rem
rem Trading-PC go-live for adopted hard-IOC → easy-GTC second-leg lock-gap policy.
rem
rem BEFORE running this:
rem   1. Merge the GitHub PR into main (base: main).
rem   2. Run this from the TBN_Report clone root on the trading PC.
rem
rem What this does:
rem   - Fetches / pulls latest main
rem   - Backs up tools\live_lock_orders.py if the local copy differs from git
rem     (trading-PC thin-first / flatten_filled_leg must NOT be wiped)
rem   - Enables orders the kitchen-safe way (orders_enabled.on stamp)
rem   - Restarts the lock job when a known control script exists; else prints steps
rem
rem Manual thin-first merge (if backup/diff warns):
rem   Keep trading-PC: hard/thin-first leg picker (_pick_hard_leg / size-first),
rem   flatten_filled_leg helper, any NET_MAX / leftover latch live-only bits.
rem   Take from git: GTC second-leg TIF, _send_pair hard IOC then easy GTC,
rem   tick_one_leg_gtc_watches (cancel + exit/BE), cancel_second_leg_gtc_on_resolve,
rem   orders_enabled() / LOCK_ORDERS_ENABLED / stamp gate, Polymarket GTC
rem   synchronousExecution=false.
rem =============================================================================
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "FAIL=0"
set "LOCK_PY=tools\live_lock_orders.py"
set "STAMP_RAW=drive\paul_experiments\prediction_market_arb_exhaustive_20261017\raw"
set "STAMP_ON=%STAMP_RAW%\orders_enabled.on"
set "STAMP_OFF=%STAMP_RAW%\orders_enabled.off"
set "BACKUP_DIR=tools\_live_lock_backup"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "TS=%%i"

echo === Lock-gap GTC second-leg: trading PC merge / enable ===
echo Repo root: %CD%
echo.

where git >nul 2>&1
if errorlevel 1 (
  echo ERROR: git not on PATH.
  exit /b 1
)

echo --- 1) git fetch / checkout main / pull ---
git fetch origin main
if errorlevel 1 (
  echo ERROR: git fetch failed.
  exit /b 1
)
git rev-parse --abbrev-ref HEAD > "%TEMP%\tbn_lock_branch.txt" 2>nul
set /p CUR_BRANCH=<"%TEMP%\tbn_lock_branch.txt"
if /i not "%CUR_BRANCH%"=="main" (
  echo NOTE: current branch is "%CUR_BRANCH%". Switching to main.
  git checkout main
  if errorlevel 1 (
    echo ERROR: could not checkout main. Merge the PR on GitHub first, then retry.
    exit /b 1
  )
)
git pull origin main
if errorlevel 1 (
  echo ERROR: git pull origin main failed. Resolve conflicts, then re-run.
  exit /b 1
)

echo.
echo --- 2) Backup / thin-first guard for %LOCK_PY% ---
if not exist "%LOCK_PY%" (
  echo ERROR: %LOCK_PY% missing after pull.
  exit /b 1
)
if not exist "%BACKUP_DIR%" mkdir "%BACKUP_DIR%"
set "BACKUP=%BACKUP_DIR%\live_lock_orders.py.%TS%.bak"
copy /Y "%LOCK_PY%" "%BACKUP%" >nul
echo Backed up working copy to %BACKUP%

rem Detect likely thin-first live-only symbols still present after pull.
findstr /C:"flatten_filled_leg" /C:"_pick_hard_leg" /C:"thin_first" "%LOCK_PY%" >nul 2>&1
if not errorlevel 1 (
  echo OK: git tree copy still mentions thin-first / flatten helpers.
) else (
  echo.
  echo WARNING: %LOCK_PY% from git may NOT include trading-PC thin-first /
  echo          flatten_filled_leg. If your pre-pull live file had those, restore
  echo          from backup and manually merge GTC second-leg onto it:
  echo            %BACKUP%
  echo          Keep: thin-first hard-leg picker + flatten_filled_leg.
  echo          Take from git/main: GTC second leg, watch tick exits, resolve-cancel,
  echo          orders_enabled^(^) stamp/env gate, Polymarket GTC sync=false.
  echo.
)

echo.
echo --- 3) Enable orders ^(kitchen stamp^) ---
if not exist "%STAMP_RAW%" mkdir "%STAMP_RAW%"
if exist "%STAMP_OFF%" (
  echo Removing %STAMP_OFF% ^(off stamp always wins^).
  del /F /Q "%STAMP_OFF%"
)
echo on>"%STAMP_ON%"
echo Wrote %STAMP_ON%
echo Optional process env ^(if you launch the job yourself^): set LOCK_ORDERS_ENABLED=1
echo.

echo --- 4) Restart lock job ---
if exist "tools\prediction_job_control.py" (
  echo Found tools\prediction_job_control.py — attempting restart-lock.
  python tools\prediction_job_control.py restart-lock
  if errorlevel 1 (
    echo WARNING: restart-lock returned non-zero. Restart the lock supervisor manually.
    set "FAIL=1"
  ) else (
    echo restart-lock OK.
  )
) else (
  echo No tools\prediction_job_control.py in this clone.
  echo Manual restart ^(typical trading PC^):
  echo   - Stop the live lock / overnight_scan lock worker
  echo   - Confirm %STAMP_ON% exists and %STAMP_OFF% does not
  echo   - Start the lock job again so it reloads live_lock_orders.py
  echo   - Watch logs for: "second-leg GTC resting" and watch-tick lines after 180s
)

echo.
if "%FAIL%"=="1" (
  echo DONE with warnings. Review backup and restart.
  exit /b 1
)
echo DONE. Policy doc: docs\lock_gap_gtc_second_leg_adopt_20261031.html
exit /b 0
