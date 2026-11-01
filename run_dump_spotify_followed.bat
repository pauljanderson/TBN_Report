@echo off
setlocal
python "%~dp0tools\dump_spotify_followed.py" %*
exit /b %errorlevel%
