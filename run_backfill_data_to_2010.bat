@echo off
rem One-time backfill: extend CSV history to START_DATE (2010-01-01) for files that start later.
rem After this completes, run_update_data.bat stays incremental (only recent bars).
rem This may take a long time on first run (full re-download for symbols missing pre-2016 history).
setlocal EnableExtensions
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1
echo Backfilling OHLCV history to 2010-01-01 (auto-detect symbols needing full download)...
"%PY%" stock_analysis\pygetallMore.py --mode incremental
exit /b %errorlevel%
