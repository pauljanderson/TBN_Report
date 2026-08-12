@echo off
rem Short alias → Qullamaggie HTF / EP (TBN-hosted qull_mode) — CANONICAL
rem Implementation: run_qullamaggie_htf.bat → rocket_tbn -v qull_mode=true
rem Standalone alternate (no rocket_tbn): run_qull_standalone.bat
rem Docs: drive\paul_experiments\tbn_new_systems\qull_ep_htf\HOW_TO_RUN.md
rem Universe: drive\universes\QULL_universe.csv (default * = full scan)
rem Override: run_qull.bat path\to\test_universe.csv
rem          set QULL_UNIVERSE_CSV=... / set QULL_SYMBOLS=...
rem Full universe (all data\newdata\data\*.csv) — no env vars:
rem   run_qull.bat ALL
rem   run_qull.bat --all
rem   run_qull.bat "*"          (quote * in PowerShell; bare * often expands)
rem Legacy env: set QULL_SYMBOLS=* / ALL / set QULL_ALL_CSV=1
rem Extra CLI args (%*) are forwarded (leading .csv / ALL stripped; -v kept).
setlocal EnableExtensions
cd /d "%~dp0"
echo [QULL] run_qull.bat → run_qullamaggie_htf.bat → rocket_tbn -v qull_mode=true
call "%~dp0run_qullamaggie_htf.bat" %*
exit /b %errorlevel%
