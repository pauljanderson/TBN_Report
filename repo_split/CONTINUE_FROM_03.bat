@echo off
rem Resume after 02_move_tbn succeeded (or mostly succeeded).
rem Runs: extract Predictions + Spotify -> rewrite paths -> github -> verify.
setlocal EnableExtensions
cd /d "%~dp0"

set "TBN=C:\Users\songg\code\TBN"
if not exist "%TBN%\.git" (
  echo FAIL: %TBN%\.git missing — 02 copy did not land. Re-run 02_move_tbn.bat
  if not defined REPO_SPLIT_NOPAUSE pause
  exit /b 1
)
if not exist "%TBN%\DailyRun.bat" (
  echo FAIL: %TBN%\DailyRun.bat missing
  if not defined REPO_SPLIT_NOPAUSE pause
  exit /b 1
)

echo TBN looks present at %TBN%
echo Continuing with extract / rewrite / github / verify...
echo.
set "REPO_SPLIT_NOPAUSE=1"

call "%~dp003_extract_predictions.bat"
if errorlevel 1 goto :fail
call "%~dp004_extract_spotify.bat"
if errorlevel 1 goto :fail
call "%~dp005_rewrite_paths.bat"
if errorlevel 1 goto :fail
call "%~dp006_github_remotes.bat"
if errorlevel 1 goto :fail
call "%~dp008_verify.bat"
if errorlevel 1 goto :fail

echo.
echo ============================================
echo  Continue-from-03 complete.
echo  Smoke-test, then run 07_prune_tbn.bat
echo ============================================
pause
exit /b 0

:fail
echo.
echo FAILED — fix above, re-run CONTINUE_FROM_03.bat
pause
exit /b 1
