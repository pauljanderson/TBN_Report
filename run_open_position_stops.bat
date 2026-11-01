@echo off
rem Open-position stop check. Research helper only. Not DailyRun.
rem Prints the stop to use now, or a missed sale, for gettarget_positions.csv.
rem
rem   run_open_position_stops.bat

setlocal EnableExtensions
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

"%PY%" -u "%~dp0tools\open_position_stops.py"
set RC=%ERRORLEVEL%
echo.
if not "%RC%"=="0" echo Open position stops failed. Exit %RC%.
exit /b %RC%
