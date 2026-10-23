@echo off
setlocal
python "%~dp0tools\sync_spotify_year_playlists.py" %*
exit /b %errorlevel%
