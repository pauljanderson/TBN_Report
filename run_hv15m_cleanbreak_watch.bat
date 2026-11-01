@echo off
rem Clean-break live watch for the filter in hv15m_cleanbreak_stop_grid_20260927.
rem The zone is still the 15-minute high-volume candle. The signal bar is 10 minutes.
rem
rem One pass right now (double-click, no arguments):
rem   run_hv15m_cleanbreak_watch.bat
rem
rem Morning loop. On a weekday it waits until 9:40 Eastern Time if started
rem earlier, then runs every 10 minutes through 11:10, and exits:
rem   9:40, 9:50, 10:00, 10:10, 10:20, 10:30, 10:40, 10:50, 11:00, 11:10
rem   run_hv15m_cleanbreak_watch.bat loop
rem
rem A phone notification (ntfy) is sent only when a symbol is triggered to buy.
rem The same symbol and the same signal bar are not sent again. A refresh with
rem no new buy does not notify. If the phone post fails, the next pass tries
rem that buy again.
rem
rem Task Scheduler (weekdays), action:
rem   Program:  C:\Users\songg\Downloads\stockresearch\run_hv15m_cleanbreak_watch.bat
rem   Args:     loop
rem   Start in: C:\Users\songg\Downloads\stockresearch
rem   Trigger:  9:38am weekdays. The window runs at 9:40 and stays through 11:10.

setlocal EnableExtensions
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

set "ALERT=%~dp0drive\paul_experiments\hv15m_cleanbreak_stop_grid_20260927\live_buy_alert.txt"

if /I "%~1"=="loop" goto :watch_loop

"%PY%" -u "%~dp0tools\hv15m_cleanbreak_stopgrid_watch.py" --no-notify %*
set RC=%ERRORLEVEL%
call :maybe_buy
exit /b %RC%

:watch_loop
"%PY%" -u "%~dp0tools\hv15m_cleanbreak_stopgrid_watch.py" --due-now
if errorlevel 1 goto :wait_next
"%PY%" -u "%~dp0tools\hv15m_cleanbreak_stopgrid_watch.py" --no-notify
call :maybe_buy
:wait_next
"%PY%" -u "%~dp0tools\hv15m_cleanbreak_stopgrid_watch.py" --sleep-until-next
if errorlevel 1 goto :watch_done
goto :watch_loop

:watch_done
exit /b 0

:maybe_buy
if not exist "%ALERT%" exit /b 0
set "BUYMSG="
set /p BUYMSG=<"%ALERT%"
if "%BUYMSG%"=="" exit /b 0
"%PY%" -u "%~dp0tools\ntfy_job_done.py" -t "Clean break buy" -m "%BUYMSG%" > "%TEMP%\hv15m_buy_ntfy.txt" 2>&1
findstr /C:"ntfy ok" "%TEMP%\hv15m_buy_ntfy.txt" >nul
if errorlevel 1 (
  echo Buy alert was not delivered. It will be tried again on the next pass.
  type "%TEMP%\hv15m_buy_ntfy.txt"
  exit /b 0
)
del /q "%ALERT%" >nul 2>&1
echo Sent buy alert.
exit /b 0
