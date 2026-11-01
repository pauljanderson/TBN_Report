@echo off
setlocal
REM Force-push drive\spotify_upcoming_shows\state.json onto the Spotify
REM "upcoming shows" playlist (no StungEvents calls).
python "%~dp0tools\sync_spotify_upcoming_shows.py" --states MA,RI --days 120 --apply-playlist %*
exit /b %errorlevel%
