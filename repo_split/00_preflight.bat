@echo off
rem Preflight checks before the three-repo split.
setlocal EnableExtensions
cd /d "%~dp0"

set "SOURCE=%STOCKRESEARCH_SOURCE%"
if "%SOURCE%"=="" set "SOURCE=C:\Users\songg\Downloads\stockresearch"
set "CODE_ROOT=C:\Users\songg\code"
set "TBN=%CODE_ROOT%\TBN"
set "PM=%CODE_ROOT%\PredictionsMarkets"
set "SPOTIFY=%CODE_ROOT%\Spotify"

echo === Repo split preflight ===
echo Source:  %SOURCE%
echo Targets: %TBN%
echo          %PM%
echo          %SPOTIFY%
echo.

set "ERR=0"

if not exist "%SOURCE%\.git" (
  echo FAIL: source is not a git repo: %SOURCE%
  set "ERR=1"
) else (
  echo OK: source git repo found
)

if not exist "%SOURCE%\DailyRun.bat" (
  echo FAIL: DailyRun.bat missing in source
  set "ERR=1"
) else (
  echo OK: DailyRun.bat
)

if not exist "%SOURCE%\tools\live_lock_orders.py" (
  echo FAIL: prediction tools missing
  set "ERR=1"
) else (
  echo OK: prediction tools
)

if not exist "%SOURCE%\tools\sync_spotify_year_playlists.py" (
  echo FAIL: spotify tools missing
  set "ERR=1"
) else (
  echo OK: spotify tools
)

where git >nul 2>&1
if errorlevel 1 (
  echo FAIL: git not on PATH
  set "ERR=1"
) else (
  echo OK: git
)

where gh >nul 2>&1
if errorlevel 1 (
  echo WARN: gh not on PATH — 06_github_remotes.bat will need GitHub CLI
) else (
  echo OK: gh
  gh auth status 2>nul
)

where python >nul 2>&1
if errorlevel 1 (
  where py >nul 2>&1
  if errorlevel 1 (
    echo FAIL: python not on PATH
    set "ERR=1"
  ) else (
    echo OK: py launcher
  )
) else (
  echo OK: python
)

echo.
if exist "%TBN%" echo WARN: %TBN% already exists
if exist "%PM%" echo WARN: %PM% already exists
if exist "%SPOTIFY%" echo WARN: %SPOTIFY% already exists

echo.
if "%ERR%"=="0" (
  echo Preflight passed. Next: 01_create_dirs.bat
) else (
  echo Preflight FAILED — fix the items above first.
)
echo.
if not defined REPO_SPLIT_NOPAUSE pause
exit /b %ERR%
