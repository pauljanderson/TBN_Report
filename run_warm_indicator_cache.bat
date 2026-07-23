@echo off
rem Pre-warm indicator disk cache (.brt_indicator_cache, INDICATOR_CACHE_VERSION=4).
rem Speeds use_indicators=true runs (IND_* / IND_TC_* on Closed); not required for correctness —
rem cold/miss rebuilds (and v3→v4 upgrades) happen inside build_entry_indicator_precompute.
rem DailyRun: skipped unless WARM_IND=1. Standalone: double-click or call after data download.
setlocal EnableExtensions
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1
"%PY%" stock_analysis\warm_indicator_cache.py data\newdata\data -w 30
exit /b %errorlevel%
