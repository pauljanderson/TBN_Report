@echo off
setlocal
python "%~dp0tools\sync_spotify_upcoming_shows.py" %*
exit /b %errorlevel%
