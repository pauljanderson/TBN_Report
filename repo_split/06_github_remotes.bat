@echo off
rem Init git in PredictionsMarkets + Spotify, create GitHub repos, push.
rem TBN keeps existing remote pauljanderson/TBN_Report (already wired).
rem
rem Requires: gh auth login
setlocal EnableExtensions
cd /d "%~dp0"

set "TBN=C:\Users\songg\code\TBN"
set "PM=C:\Users\songg\code\PredictionsMarkets"
set "SPOTIFY=C:\Users\songg\code\Spotify"
set "OWNER=pauljanderson"

where gh >nul 2>&1
if errorlevel 1 (
  echo FAIL: GitHub CLI ^(gh^) not found. Install from https://cli.github.com/
if not defined REPO_SPLIT_NOPAUSE pause
  exit /b 1
)

gh auth status
if errorlevel 1 (
  echo Run: gh auth login
if not defined REPO_SPLIT_NOPAUSE pause
  exit /b 1
)

echo.
echo === TBN remote (should already be TBN_Report) ===
if exist "%TBN%\.git" (
  pushd "%TBN%"
  git remote -v
  popd
) else (
  echo WARN: %TBN%\.git missing
)

echo.
echo === PredictionsMarkets ===
if not exist "%PM%\tools\live_lock_orders.py" (
  echo FAIL: run 03_extract_predictions.bat first
if not defined REPO_SPLIT_NOPAUSE pause
  exit /b 1
)
pushd "%PM%"
if not exist ".git" (
  git init -b main
  git add -A
  git commit -m "Initial import: PredictionsMarkets split from stockresearch monorepo"
)
gh repo view "%OWNER%/PredictionsMarkets" >nul 2>&1
if errorlevel 1 (
  echo Creating private GitHub repo %OWNER%/PredictionsMarkets ...
  gh repo create "%OWNER%/PredictionsMarkets" --private --source=. --remote=origin --push
) else (
  echo Repo already exists — setting origin and pushing...
  git remote remove origin 2>nul
  git remote add origin "https://github.com/%OWNER%/PredictionsMarkets.git"
  git push -u origin main
)
popd

echo.
echo === Spotify ===
if not exist "%SPOTIFY%\tools\sync_spotify_year_playlists.py" (
  echo FAIL: run 04_extract_spotify.bat first
if not defined REPO_SPLIT_NOPAUSE pause
  exit /b 1
)
pushd "%SPOTIFY%"
if not exist ".git" (
  git init -b main
  git add -A
  git commit -m "Initial import: Spotify split from stockresearch monorepo"
)
gh repo view "%OWNER%/Spotify" >nul 2>&1
if errorlevel 1 (
  echo Creating private GitHub repo %OWNER%/Spotify ...
  gh repo create "%OWNER%/Spotify" --private --source=. --remote=origin --push
) else (
  echo Repo already exists — setting origin and pushing...
  git remote remove origin 2>nul
  git remote add origin "https://github.com/%OWNER%/Spotify.git"
  git push -u origin main
)
popd

echo.
echo Remotes:
echo   TBN:               https://github.com/%OWNER%/TBN_Report
echo   PredictionsMarkets:https://github.com/%OWNER%/PredictionsMarkets
echo   Spotify:           https://github.com/%OWNER%/Spotify
echo.
echo Next: 08_verify.bat  ^(then 07_prune_tbn.bat after you confirm systems run^)
if not defined REPO_SPLIT_NOPAUSE pause
exit /b 0
