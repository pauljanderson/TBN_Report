@echo off
rem =============================================================================
rem merge_thin_first_into_gtc.bat
rem
rem STEP 2 of trading-PC lock-gap merge: re-paste thin-first from backup into
rem clean GTC tools\live_lock_orders.py (after step 1: backup + checkout --theirs).
rem
rem Prerequisites:
rem   - cwd is the stockresearch / TBN_Report repo root (or C:\Users\songg\Downloads\stockresearch)
rem   - tools\_merge_backup\live_lock_orders.py exists (conflicted / pre-theirs copy
rem     that still contains _pick_hard_leg / thin-first)
rem   - tools\live_lock_orders.py is the clean GTC file from origin/main
rem
rem What this does:
rem   - Refuses if backup missing
rem   - Backs up current live file to tools\_merge_backup\live_lock_orders.before_thin_merge.py
rem   - Runs tools\merge_thin_first_into_gtc.py to extract thin-first and inject into GTC
rem   - findstr checks for thin-first AND GTC symbols
rem   - Optionally runs python tools\test_live_lock_orders.py
rem   - Prints next steps (git add/commit, then merge_lock_gap_gtc_live.bat)
rem =============================================================================
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

rem Prefer Paul's trading-PC path when this bat was copied elsewhere / double-clicked
if exist "C:\Users\songg\Downloads\stockresearch\tools\live_lock_orders.py" (
  if not exist "%~dp0tools\live_lock_orders.py" (
    cd /d "C:\Users\songg\Downloads\stockresearch"
  )
)
if exist "tools\live_lock_orders.py" goto :have_root
if exist "C:\Users\songg\Downloads\stockresearch\tools\live_lock_orders.py" (
  cd /d "C:\Users\songg\Downloads\stockresearch"
)
:have_root

set "FAIL=0"
set "LOCK_PY=tools\live_lock_orders.py"
set "BACKUP=tools\_merge_backup\live_lock_orders.py"
set "HELPER=tools\merge_thin_first_into_gtc.py"
set "BEFORE=tools\_merge_backup\live_lock_orders.before_thin_merge.py"
set "RUN_UNIT=1"
if /I "%~1"=="--skip-tests" set "RUN_UNIT=0"
if /I "%~1"=="--dry-run" set "DRY=1"
if /I "%~1"=="--self-test" set "SELFTEST=1"

echo === STEP 2: merge thin-first into clean GTC live_lock_orders.py ===
echo Repo root: %CD%
echo.

if not exist "%HELPER%" (
  echo ERROR: %HELPER% missing. Copy merge_thin_first_into_gtc.bat AND
  echo        tools\merge_thin_first_into_gtc.py into this repo root, then re-run.
  exit /b 1
)

where python >nul 2>&1
if errorlevel 1 (
  echo ERROR: python not on PATH.
  exit /b 1
)

if defined SELFTEST (
  echo --- self-test ^(synthetic conflicted snippets^) ---
  python "%HELPER%" --self-test
  exit /b %ERRORLEVEL%
)

if not exist "%BACKUP%" (
  echo ERROR: backup missing: %BACKUP%
  echo.
  echo Step 1 must leave your conflicted / pre-theirs trading-PC copy there:
  echo   mkdir tools\_merge_backup 2^>nul
  echo   copy /Y tools\live_lock_orders.py tools\_merge_backup\live_lock_orders.py
  echo   git checkout --theirs -- tools\live_lock_orders.py
  echo     ^(and the other conflicted files^)
  echo Then re-run this bat. The helper will NOT invent thin-first from main.
  exit /b 2
)

if not exist "%LOCK_PY%" (
  echo ERROR: %LOCK_PY% missing. Finish step 1 ^(checkout --theirs^) first.
  exit /b 1
)

echo --- 0^) preflight findstr ---
findstr /C:"_pick_hard_leg" "%BACKUP%" >nul 2>&1
if errorlevel 1 (
  echo ERROR: %BACKUP% has no _pick_hard_leg.
  echo        That backup must be the conflicted/local thin-first copy, not clean main.
  exit /b 2
)
echo OK: backup mentions _pick_hard_leg

findstr /C:"ONE_LEG_GTC_WAIT_SEC" /C:"_with_tif" "%LOCK_PY%" >nul 2>&1
if errorlevel 1 (
  echo ERROR: %LOCK_PY% does not look like clean GTC from main.
  echo        Expected ONE_LEG_GTC_WAIT_SEC / _with_tif. Re-do step 1 checkout --theirs.
  exit /b 1
)
echo OK: current live file looks like GTC

echo.
if defined DRY (
  echo --- dry-run merge ^(no write^) ---
  python "%HELPER%" --dry-run --backup "%BACKUP%" --gtc "%LOCK_PY%"
  if errorlevel 1 (
    echo FAIL: dry-run merge failed. See messages above.
    exit /b 1
  )
  echo.
  echo Dry-run OK. Re-run without --dry-run to write %LOCK_PY%.
  exit /b 0
)

echo --- 1^) safety backup of current GTC live file ---
if not exist "tools\_merge_backup" mkdir "tools\_merge_backup"
copy /Y "%LOCK_PY%" "%BEFORE%" >nul
if errorlevel 1 (
  echo ERROR: could not write %BEFORE%
  exit /b 1
)
echo Wrote %BEFORE%

echo.
echo --- 2^) Python extract / inject ---
python "%HELPER%" --backup "%BACKUP%" --gtc "%LOCK_PY%" --out "%LOCK_PY%" --no-before-backup
if errorlevel 1 (
  echo.
  echo FAIL: merge helper failed. Live file may be unchanged or partial.
  echo Restore GTC from: %BEFORE%
  echo Then either fix the backup conflict markers, or manually paste
  echo _pick_hard_leg / flatten_filled_leg from backup into the GTC file.
  exit /b 1
)

echo.
echo --- 3^) findstr thin-first + GTC ---
set "CHK_FAIL=0"
call :check_sym "_pick_hard_leg"
call :check_sym "_with_tif"
call :check_sym "ONE_LEG_GTC_WAIT_SEC"
call :check_sym "CHEAP_EXIT_MAX"
call :check_sym "tick_one_leg_gtc_watches"
call :check_sym "cancel_second_leg_gtc_on_resolve"
call :check_sym "orders_enabled"
findstr /C:"outcomes = _pick_hard_leg" "%LOCK_PY%" >nul 2>&1
if errorlevel 1 (
  echo FAIL: send path still not calling _pick_hard_leg
  set "CHK_FAIL=1"
) else (
  echo OK: outcomes = _pick_hard_leg
)
findstr /C:"flatten_filled_leg" "%LOCK_PY%" >nul 2>&1
if errorlevel 1 (
  echo NOTE: flatten_filled_leg not found ^(optional if backup lacked a top-level def^)
) else (
  echo OK: flatten_filled_leg
)
findstr /C:"synchronousExecution" "%LOCK_PY%" >nul 2>&1
if errorlevel 1 (
  echo NOTE: synchronousExecution string not found via findstr ^(Poly GTC may still be present^)
) else (
  echo OK: synchronousExecution
)

if "%CHK_FAIL%"=="1" (
  echo.
  echo FAIL: symbol checks failed. Restore from %BEFORE% and merge manually.
  set "FAIL=1"
)

echo.
if "%RUN_UNIT%"=="1" (
  if exist "tools\test_live_lock_orders.py" (
    echo --- 4^) python tools\test_live_lock_orders.py ---
    python tools\test_live_lock_orders.py
    if errorlevel 1 (
      echo WARNING: unit tests failed. Review %LOCK_PY% before committing.
      set "FAIL=1"
    ) else (
      echo OK: test_live_lock_orders.py
    )
  ) else (
    echo NOTE: tools\test_live_lock_orders.py not present; skipped.
  )
) else (
  echo --- 4^) unit tests skipped ^(--skip-tests^) ---
)

echo.
echo === NEXT STEPS ===
echo   1. Spot-check tools\live_lock_orders.py: _pick_hard_leg + GTC second-leg still there.
echo   2. Commit the merge (do not leave a half-merged working tree^):
echo        git add tools\live_lock_orders.py
echo        git status
echo        git commit -m "Merge thin-first into GTC live_lock_orders"
echo   3. Then run go-live:
echo        merge_lock_gap_gtc_live.bat
echo.
echo Safety copies:
echo   thin-first source: %BACKUP%
echo   pre-merge GTC:     %BEFORE%
echo.

if "%FAIL%"=="1" (
  echo DONE with FAIL/warnings.
  exit /b 1
)
echo DONE. STEP 2 OK.
exit /b 0

:check_sym
findstr /C:"%~1" "%LOCK_PY%" >nul 2>&1
if errorlevel 1 (
  echo FAIL: missing %~1
  set "CHK_FAIL=1"
) else (
  echo OK: %~1
)
exit /b 0
