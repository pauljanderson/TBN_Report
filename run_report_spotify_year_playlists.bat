@echo off
setlocal
python "%~dp0tools\report_spotify_year_playlists.py" %*
exit /b %errorlevel%
