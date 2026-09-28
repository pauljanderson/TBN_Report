@echo off
rem Clean-break live watch for the filter in hv15m_cleanbreak_stop_grid_20260927.
rem
rem One pass (Task Scheduler, or double-click at 9:40, 9:45, and every 15 minutes):
rem   run_hv15m_cleanbreak_watch.bat
rem
rem Leave a window open for the whole morning. It runs at 9:40, again at 9:45,
rem then every 15 minutes through 11:15 Eastern, weekdays:
rem   run_hv15m_cleanbreak_watch.bat loop
rem
rem 9:40 draws 1-minute charts for names close to the trigger while the 9:30
rem bar is still forming. 9:45 and each later slot check whether that
rem 15-minute bar closed as a buy. A phone alert is sent only when a new
rem signal prints.
rem
rem Task Scheduler (weekdays), action:
rem   Program:  C:\Users\songg\Downloads\stockresearch\run_hv15m_cleanbreak_watch.bat
rem   Args:     loop
rem   Start in: C:\Users\songg\Downloads\stockresearch
rem   Trigger:  9:38am weekdays. The window waits until 9:40, then stays through 11:15.

setlocal EnableExtensions
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

if /I "%~1"=="loop" (
  "%PY%" -u tools\hv15m_cleanbreak_stopgrid_watch.py --loop
  exit /b %ERRORLEVEL%
)

"%PY%" -u tools\hv15m_cleanbreak_stopgrid_watch.py %*
exit /b %ERRORLEVEL%
