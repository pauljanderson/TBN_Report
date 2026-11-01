@echo off
rem Back-compat wrapper. Prefer run_pm_venue_kitchen_check.bat (all platforms).
rem Optional first arg: kitchen Kalshi-closed window P&L, e.g. -0.90

setlocal
cd /d "%~dp0"
call "%~dp0run_pm_venue_kitchen_check.bat" %*
exit /b %ERRORLEVEL%
