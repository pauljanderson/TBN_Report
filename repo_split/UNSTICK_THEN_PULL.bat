@echo off
rem One-shot: stash local WIP, checkout main, pull (gets repo_split), restore WIP.
rem Run from repo root OR from repo_split\ (will cd to parent if needed).
setlocal EnableExtensions
cd /d "%~dp0"
if exist "%~dp0..\git_pull.bat" cd /d "%~dp0.."

echo === Unstick: stash -> main -> pull -> stash pop ===
echo.

git status -sb
echo.

echo Stashing local edits (including untracked)...
git stash push -u -m "pre-repo-split local PM WIP"
if errorlevel 1 (
  echo Stash failed.
  pause
  exit /b 1
)

echo.
git checkout main
if errorlevel 1 (
  echo checkout main failed — recovering stash...
  git stash pop
  pause
  exit /b 1
)

git pull origin main
if errorlevel 1 (
  echo pull failed — recovering stash...
  git stash pop
  pause
  exit /b 1
)

echo.
echo Restoring your local edits on top of updated main...
git stash pop
if errorlevel 1 (
  echo Stash pop conflicts — fix files, then: git add -A ^& git commit
  pause
  exit /b 1
)

echo.
echo === Done ===
git log -1 --oneline
if exist "repo_split\RUN_ALL.bat" (
  echo repo_split is on disk. Next:
  echo   cd repo_split
  echo   RUN_ALL.bat
) else (
  echo WARN: repo_split\RUN_ALL.bat still missing — pull may not have main tip.
)
echo.
pause
exit /b 0
