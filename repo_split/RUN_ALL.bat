@echo off
rem Run the full split sequence (copy TBN → extract → rewrite → github → verify).
rem Does NOT prune TBN or delete Downloads\stockresearch — do those after smoke tests.
setlocal EnableExtensions
cd /d "%~dp0"

echo ============================================
echo  Three-repo split: TBN / Predictions / Spotify
echo ============================================
echo.
echo This will:
echo  1. Create C:\Users\songg\code\*
echo  2. COPY Downloads\stockresearch -^> code\TBN
echo  3. Extract PredictionsMarkets + Spotify
echo  4. Rewrite hardcoded stockresearch paths
echo  5. Create/push GitHub repos ^(needs gh auth^)
echo  6. Verify layouts
echo.
echo It will NOT prune TBN or delete the Downloads folder.
echo.
set /p "ANS=Type GO to continue: "
if /i not "%ANS%"=="GO" (
  echo Aborted.
  if not defined REPO_SPLIT_NOPAUSE pause
  exit /b 1
)

rem Children skip their own pause prompts while we chain.
set "REPO_SPLIT_NOPAUSE=1"

call "%~dp000_preflight.bat"
if errorlevel 1 goto :fail

call "%~dp001_create_dirs.bat"
call "%~dp002_move_tbn.bat"
if errorlevel 1 goto :fail
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
echo  Split complete. Smoke-test, then run 07_prune_tbn.bat
echo ============================================
if not defined REPO_SPLIT_NOPAUSE pause
exit /b 0

:fail
echo.
echo FAILED — fix the error above, then re-run from the failed step.
if not defined REPO_SPLIT_NOPAUSE pause
exit /b 1
