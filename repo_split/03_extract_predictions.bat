@echo off
rem Extract PredictionsMarkets files from TBN into C:\Users\songg\code\PredictionsMarkets
setlocal EnableExtensions
cd /d "%~dp0"

set "TBN=C:\Users\songg\code\TBN"
set "PM=C:\Users\songg\code\PredictionsMarkets"
set "PY=python"

where python >nul 2>&1
if errorlevel 1 set "PY=py"

if not exist "%TBN%\tools\live_lock_orders.py" (
  echo FAIL: TBN not ready at %TBN% — run 02_move_tbn.bat first
if not defined REPO_SPLIT_NOPAUSE pause
  exit /b 1
)

echo === Extract PredictionsMarkets ===
"%PY%" "%~dp0lib\split_copy.py" --target predictions --source "%TBN%" --dest "%PM%" --runtime
if errorlevel 1 (
  echo Extract finished with missing files — review output.
)

echo.
echo Next: 04_extract_spotify.bat
if not defined REPO_SPLIT_NOPAUSE pause
exit /b 0
