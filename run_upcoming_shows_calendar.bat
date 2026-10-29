@echo off
setlocal
REM Build HTML calendar from drive\spotify_upcoming_shows\state.json (0 Spotify / Stung calls)
python "%~dp0tools\report_spotify_upcoming_shows_calendar.py" --open %*
exit /b %errorlevel%
