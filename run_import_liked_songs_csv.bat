@echo off
setlocal
REM Import Liked Songs CSV → drive\spotify_library_cache\library.json (0 Spotify calls)
REM Default looks for drive\spotify_library_cache\Liked_Songs.csv
REM Or pass a path: run_import_liked_songs_csv.bat "C:\Users\songg\Downloads\Liked_Songs (4).csv"
python "%~dp0tools\import_liked_songs_csv.py" %*
exit /b %errorlevel%
