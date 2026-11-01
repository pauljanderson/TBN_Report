@echo off
setlocal
REM Append Album-of-the-Year highest-rated matches to "{year} listen".
REM
REM Setup (once):
REM   1. Copy tools\aoty_listen_config.example.json → drive\spotify_aoty_listen\config.json
REM      (first run also seeds this automatically).
REM   2. In a browser, open AOTY highest-rated pages for the year, e.g.
REM        https://www.albumoftheyear.org/ratings/6-highest-rated/2026/1
REM        …/2026/2 … through max_pages (default 6 ≈ top 150).
REM      Save each page as HTML (or copy-as-markdown .md) into
REM        drive\spotify_aoty_listen\pages\
REM      Cloudflare blocks curl/requests — do not try to scrape from this PC's CLI.
REM
REM Shares "{year} listen" with sync_spotify_year_listen.py. Year-listen rebuilds
REM re-merge AOTY albums from drive\spotify_aoty_listen\state.json so they are not wiped.
REM
REM Safe defaults: min_score=70, min_reviews=5, max_albums_per_run=20, ~80 Spotify calls/UTC-day.
REM Tip: run with --dry-run first to review AOTY → Spotify matches.
python "%~dp0tools\sync_spotify_aoty_listen.py" %*
exit /b %errorlevel%
