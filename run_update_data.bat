@echo off
rem Incremental OHLCV update (pygetallMore) — DailyRun step 1
rem First run after START_DATE=2010 change auto-backfills symbols that still start at 2016.
rem For a dedicated one-time backfill, use run_backfill_data_to_2010.bat instead.
setlocal EnableExtensions
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1
"%PY%" stock_analysis\pygetallMore.py
exit /b %errorlevel%
