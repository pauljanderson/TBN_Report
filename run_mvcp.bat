@echo off
rem Short alias → Minervini VCP (MVCP)
rem Canonical implementation: run_minervini_vcp.bat
rem Docs: drive\paul_experiments\tbn_new_systems\minervini_vcp\HOW_TO_RUN.html
rem Universe: drive\universes\MVCP_universe.csv (default * = full scan)
rem Override: run_mvcp.bat path\to\test_universe.csv
rem          set MVCP_UNIVERSE_CSV=... / set MVCP_SYMBOLS=...
rem Full universe (all data\newdata\data\*.csv) — no env vars:
rem   run_mvcp.bat ALL
rem   run_mvcp.bat --all
rem   run_mvcp.bat "*"          (quote * in PowerShell; bare * often expands)
rem Legacy env: set MVCP_SYMBOLS=* / ALL / set MVCP_ALL_CSV=1
rem Extra CLI args (%*) are forwarded (aggressive ON by default via MVCP_AGGRESSIVE=true).
rem Workers: MVCP_WORKERS (default 12) or trailing -w N.
setlocal EnableExtensions
cd /d "%~dp0"
call "%~dp0run_minervini_vcp.bat" %*
exit /b %errorlevel%
