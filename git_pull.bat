@echo off
rem Pull the latest main from GitHub onto this PC.
rem Double-click after the cloud agent pushes, or any time you want to sync.
rem The agent cannot pull on your machine — this is the one-click local step.
setlocal EnableExtensions
cd /d "%~dp0"

echo === git pull origin main ===
echo.

git checkout main
if errorlevel 1 (
  echo Could not switch to main.
  goto :done
)

git pull origin main
if errorlevel 1 (
  echo.
  echo Pull failed. If you have local edits, commit or stash them first,
  echo or run git_checkin.bat then try this again.
  goto :done
)

echo.
echo Up to date with origin/main.
git log -1 --oneline

:done
echo.
pause
exit /b 0
