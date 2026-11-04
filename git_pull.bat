@echo off
rem Pull the latest main from GitHub onto this PC.
rem Double-click after the cloud agent pushes, or any time you want to sync.
rem The agent cannot pull on your machine — this is the one-click local step.
rem
rem ALWAYS run this BEFORE any new run_*.bat the agent just named. Merging a
rem PR on GitHub does not put new bats on disk — only git pull does. If Windows
rem says a bat is "not recognized", you skipped this step.
rem
rem IMPORTANT: git pull updates Python writers only. Drive dashboard.html /
rem orders_performance.html are generated stamps — they do NOT refresh until
rem write_orders_performance runs (fill/close debounce, or this bat's rebuild).
rem Fallback after pull: python tools\write_orders_performance.py
setlocal EnableExtensions
cd /d "%~dp0"

echo === git pull origin main ===
echo New bats from a merged PR are NOT on disk until this pull finishes.
echo.

rem Dirty tree blocks "git checkout main". Stash first, restore after pull.
set "DID_STASH=0"
git status --porcelain | findstr /r "." >nul
if not errorlevel 1 (
  echo Local edits detected — stashing before checkout main...
  git stash push -u -m "git_pull auto-stash before checkout main"
  if errorlevel 1 (
    echo Stash failed. Commit manually, then retry.
    goto :done
  )
  set "DID_STASH=1"
)

git checkout main
if errorlevel 1 (
  echo Could not switch to main.
  if "%DID_STASH%"=="1" git stash pop
  goto :done
)

git pull origin main
if errorlevel 1 (
  echo.
  echo Pull failed. If you have local edits, commit or stash them first,
  echo or run git_checkin.bat then try this again.
  if "%DID_STASH%"=="1" (
    echo Restoring your stash...
    git stash pop
  )
  goto :done
)

if "%DID_STASH%"=="1" (
  echo.
  echo Restoring stashed local edits onto updated main...
  git stash pop
  if errorlevel 1 (
    echo Stash pop had conflicts — fix them, then git add / commit.
    goto :done
  )
)

echo.
echo Up to date with origin/main.
git log -1 --oneline

rem Code change ≠ regenerated HTML. Rebuild kitchen stamps when local tape exists.
set "ORDERS=local\paul_experiments\prediction_market_arb_exhaustive_20261017\raw\orders.jsonl"
echo.
if exist "%ORDERS%" (
  echo === rebuild kitchen dashboard after pull ===
  echo git pull alone does not rewrite dashboard.html — running writers now.
  call "%~dp0run_rebuild_kitchen_dashboard.bat"
  if errorlevel 1 (
    echo Kitchen rebuild failed — open run_rebuild_kitchen_dashboard.bat and fix.
  )
) else (
  echo No local orders.jsonl here — skip HTML rebuild.
  echo On the trading PC after pull, run run_rebuild_kitchen_dashboard.bat
  echo so Size @ price / Gibson corrections appear on Drive dashboard.html.
)

:done
echo.
pause
exit /b 0
