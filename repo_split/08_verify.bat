@echo off
rem Check that all three repos have the files they need.
setlocal EnableExtensions
cd /d "%~dp0"

set "TBN=C:\Users\songg\code\TBN"
set "PM=C:\Users\songg\code\PredictionsMarkets"
set "SPOTIFY=C:\Users\songg\code\Spotify"
set "PY=python"
where python >nul 2>&1
if errorlevel 1 set "PY=py"

echo === Verify layouts ===
"%PY%" "%~dp0lib\verify_layout.py" --tbn "%TBN%" --pm "%PM%" --spotify "%SPOTIFY%"
set "RC=%ERRORLEVEL%"

echo.
echo Manual smoke tests ^(run when ready^):
echo   TBN:  %TBN%\run_brt.bat   ^(or a short DailyRun with SKIP flags^)
echo   PM:   %PM%\run_prediction_status.bat
echo   PM:   %PM%\run_pm_venue_kitchen_check.bat
echo   Spotify: %SPOTIFY%\run_dump_spotify_followed.bat
echo.
echo Task Scheduler: retarget DailyRun to %TBN%\DailyRun.bat
echo Cursor: File ^> Open Folder on each of the three roots ^(or a multi-root workspace^)
echo.
if "%RC%"=="0" (
  echo VERIFY OK
) else (
  echo VERIFY FAILED
)
if not defined REPO_SPLIT_NOPAUSE pause
exit /b %RC%
