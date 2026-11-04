@echo off
rem Copy PM helper modules that older extracts missed (win_hidden, ntfy, CFB movers).
rem Safe to re-run. Prefers TBN as source; falls back to Downloads\stockresearch.
setlocal EnableExtensions
cd /d "%~dp0"

set "PM=C:\Users\songg\code\PredictionsMarkets"
set "TBN=C:\Users\songg\code\TBN"
set "SRC=%TBN%"
if not exist "%SRC%\tools\win_hidden.py" set "SRC=C:\Users\songg\Downloads\stockresearch"
if not exist "%SRC%\tools\win_hidden.py" (
  echo FAIL: win_hidden.py not found under TBN or Downloads\stockresearch
  if not defined REPO_SPLIT_NOPAUSE pause
  exit /b 1
)
if not exist "%PM%\tools" (
  echo FAIL: PredictionsMarkets tools folder missing: %PM%\tools
  if not defined REPO_SPLIT_NOPAUSE pause
  exit /b 1
)

echo Source: %SRC%
echo Dest:   %PM%
echo.

for %%F in (
  win_hidden.py
  test_win_hidden.py
  ntfy_job_done.py
  live_cfb_spread_movers.py
  live_cfb_total_movers.py
  test_live_cfb_movers.py
) do (
  if exist "%SRC%\tools\%%F" (
    copy /Y "%SRC%\tools\%%F" "%PM%\tools\%%F" >nul
    echo copied tools\%%F
  ) else (
    echo skip missing source tools\%%F
  )
)

echo.
echo Smoke:
python "%PM%\tools\prediction_job_control.py" status
if errorlevel 1 (
  echo status still failed — paste the traceback
) else (
  echo OK
)
if not defined REPO_SPLIT_NOPAUSE pause
exit /b 0
