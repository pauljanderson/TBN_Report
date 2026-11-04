@echo off
rem Copy the monorepo to C:\Users\songg\code\TBN (keeps .git, data, drive, secrets).
rem Default is COPY so Downloads\stockresearch stays as a backup until you verify.
rem Pass --move to relocate instead (only if you are NOT running bats from inside source).
rem
rem Close Cursor windows / Python / Task Scheduler jobs that lock heavy files if copy stalls.
setlocal EnableExtensions
cd /d "%~dp0"

set "SOURCE=%STOCKRESEARCH_SOURCE%"
if "%SOURCE%"=="" set "SOURCE=C:\Users\songg\Downloads\stockresearch"
set "TBN=C:\Users\songg\code\TBN"
set "DO_MOVE=0"
if /i "%~1"=="--move" set "DO_MOVE=1"

echo === Install monorepo at TBN ===
echo From: %SOURCE%
echo To:   %TBN%
echo Mode: %DO_MOVE% (1=move, 0=copy)
echo.

if not exist "%SOURCE%\.git" (
  echo FAIL: source missing or not a git repo: %SOURCE%
if not defined REPO_SPLIT_NOPAUSE pause
  exit /b 1
)

if /i "%SOURCE%"=="%TBN%" (
  echo Already at target.
if not defined REPO_SPLIT_NOPAUSE pause
  exit /b 0
)

if exist "%TBN%\.git" (
  echo %TBN% already has .git — skipping.
  echo Delete it manually if you need a fresh copy.
if not defined REPO_SPLIT_NOPAUSE pause
  exit /b 0
)

mkdir "C:\Users\songg\code" 2>nul

if "%DO_MOVE%"=="1" (
  echo MOVE requested...
  if exist "%TBN%" rmdir "%TBN%" 2>nul
  move "%SOURCE%" "%TBN%"
  if errorlevel 1 (
    echo MOVE failed. Try without --move for robocopy copy instead.
if not defined REPO_SPLIT_NOPAUSE pause
    exit /b 1
  )
  goto :ok
)

echo Robocopy mirror of source -> TBN (includes .git, data, drive, local, secrets)...
rem /MIR makes TBN match source. /XD none — we want data+drive.
robocopy "%SOURCE%" "%TBN%" /E /COPY:DAT /R:2 /W:2 /MT:8
set "RC=%ERRORLEVEL%"
if %RC% GEQ 8 (
  echo robocopy failed with code %RC%
if not defined REPO_SPLIT_NOPAUSE pause
  exit /b 1
)
echo robocopy finished with code %RC% (0-7 = success).

:ok
if not exist "%TBN%\.git" (
  echo FAIL: %TBN% has no .git
if not defined REPO_SPLIT_NOPAUSE pause
  exit /b 1
)

echo.
echo TBN ready at %TBN%
echo GitHub remote stays: pauljanderson/TBN_Report
echo Downloads source left in place as backup ^(unless you used --move^).
echo.
echo Next: 03_extract_predictions.bat
echo Also retarget Task Scheduler to %TBN%\DailyRun.bat after path rewrite.
if not defined REPO_SPLIT_NOPAUSE pause
exit /b 0
