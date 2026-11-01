@echo off
setlocal
REM Build "{year} listen" from followed-artist albums not yet on year light/medium/heavy.
REM Safe defaults: albums only (no singles), 40 discography fetches/run, 150 Spotify calls/UTC-day.
REM First-time tip: run with --dry-run, then without. Use --estimate to see call counts.
REM If budget exhausted today: --spotify-daily-budget 300  OR  --cache-only (auto headroom).
python "%~dp0tools\sync_spotify_year_listen.py" %*
exit /b %errorlevel%
