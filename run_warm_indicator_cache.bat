@echo off
rem Pre-warm indicator disk cache — DailyRun step 2
setlocal EnableExtensions
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1
"%PY%" stock_analysis\warm_indicator_cache.py data\newdata\data -w 4
exit /b %errorlevel%
