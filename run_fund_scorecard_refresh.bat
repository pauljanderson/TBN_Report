@echo off
rem Fund scorecard refresh + dated PIT history snapshot (DailyRun step 1b)
rem Skip:  set SKIP_FUND_SCORECARD=1
rem Force Yahoo (ignore TTL): set FORCE_FUND_SCORECARD=1
rem TTL days: set FUND_SCORECARD_TTL_DAYS=7  (default 7)
setlocal EnableExtensions
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1
if /i "%SKIP_FUND_SCORECARD%"=="1" (
  echo [fund-scorecard] SKIPPED - SKIP_FUND_SCORECARD=1
  exit /b 0
)
"%PY%" tools\fund_scorecard_dailyrun_refresh.py %*
exit /b %errorlevel%
