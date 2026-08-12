@echo off
rem Compatibility wrapper: PBR was renamed to WPBR. Prefer run_wpbr.bat.
rem Universe: drive\universes\WPBR_universe.csv (via run_wpbr.bat)
rem Override: run_pbr.bat path\to\test_universe.csv
rem          set WPBR_UNIVERSE_CSV=...  /  set WPBR_SYMBOLS=...
rem Full universe (all data\newdata\data\*.csv) — no env vars:
rem   run_pbr.bat ALL
rem   run_pbr.bat --all
rem   run_pbr.bat "*"          (quote * in PowerShell; bare * often expands)
rem Legacy env: set WPBR_SYMBOLS=* / ALL / set WPBR_ALL_CSV=1
rem Extra CLI args (%*) are forwarded via run_wpbr.bat (leading .csv / ALL stripped; -v kept).
call "%~dp0run_wpbr.bat" %*
exit /b %errorlevel%
