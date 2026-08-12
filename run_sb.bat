@echo off
rem Short alias → StockBee Momentum Burst
rem Canonical implementation: run_stockbee_burst.bat
rem Docs: drive\paul_experiments\tbn_new_systems\stockbee_momentum_burst\HOW_TO_RUN.html
rem Standalone: double-click or call from DailyRun.
rem Universe: drive\universes\SB_universe.csv (one ticker per line; gold 56)
rem Override: run_sb.bat path\to\test_universe.csv
rem          set SB_UNIVERSE_CSV=...
rem          set SB_SYMBOLS=AAPL,MSFT
rem Full universe (all data\newdata\data\*.csv) — no env vars:
rem   run_sb.bat ALL
rem   run_sb.bat --all
rem   run_sb.bat "*"          (quote * in PowerShell; bare * often expands)
rem Legacy env still works: set SB_SYMBOLS=* / ALL / set SB_ALL_CSV=1
rem Extra CLI args (%*) are forwarded (leading .csv / ALL stripped; -v kept).
rem   run_sb.bat -v burst_min_pct=0.05

setlocal EnableExtensions
cd /d "%~dp0"
echo [SB] run_sb.bat → run_stockbee_burst.bat → rocket_tbn -v sb_mode=true
call "%~dp0run_stockbee_burst.bat" %*
exit /b %errorlevel%
