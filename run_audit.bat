@echo off
rem Legacy AWK Rocket Launcher audit — outputs RL_* CSVs via portfolio_audit.awk
rem Override symbols: set RL_SYMBOLS=... or pass -s "SYM1,SYM2" on command line
rem DailyRun: run_audit.bat -AllowRegression -s "%RL_SYMBOLS%"
setlocal EnableExtensions
cd /d "%~dp0"
call "%~dp0daily_run_env.bat"
powershell -ExecutionPolicy Bypass -File "run_audit.ps1" %*
exit /b %ERRORLEVEL%
