@echo off
setlocal
python "%~dp0tools\organize_spotify_playlists.py" %*
exit /b %errorlevel%
