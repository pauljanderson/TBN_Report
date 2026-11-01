@echo off
setlocal
python "%~dp0tools\sync_spotify_favorites_unlistened.py" %*
exit /b %errorlevel%
