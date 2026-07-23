@echo off
rem IND ATR_RATIO / VOL_SURGE / DIAMOND weight experiments.
rem Default: 3 concurrent jobs x -w 10 (~30 symbol workers).
rem Status: drive\ind_weight_exp\status.txt
rem Results: drive\ind_weight_exp\comparison.md
setlocal EnableExtensions
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1
"%PY%" tools\run_ind_weight_experiments.py --jobs 3 --workers 10 %*
exit /b %errorlevel%
