@echo off
rem Extract Spotify files from TBN into C:\Users\songg\code\Spotify
setlocal EnableExtensions
cd /d "%~dp0"

set "TBN=C:\Users\songg\code\TBN"
set "SPOTIFY=C:\Users\songg\code\Spotify"
set "PY=python"

where python >nul 2>&1
if errorlevel 1 set "PY=py"

if not exist "%TBN%\tools\sync_spotify_year_playlists.py" (
  echo FAIL: TBN not ready at %TBN% — run 02_move_tbn.bat first
if not defined REPO_SPLIT_NOPAUSE pause
  exit /b 1
)

echo === Extract Spotify ===
"%PY%" "%~dp0lib\split_copy.py" --target spotify --source "%TBN%" --dest "%SPOTIFY%" --runtime
if errorlevel 1 (
  echo Extract finished with missing files — review output.
)

echo.
echo Next: 05_rewrite_paths.bat
if not defined REPO_SPLIT_NOPAUSE pause
exit /b 0
