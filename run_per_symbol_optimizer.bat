@echo off
rem Per-symbol BRT/RL optimizer — see stock_analysis\per_symbol_optimizer.py
rem Examples:
rem   run_per_symbol_optimizer.bat
rem   run_per_symbol_optimizer.bat --systems RL --workers 5
rem   run_per_symbol_optimizer.bat --systems BRT --symbols NVDA,TSLA --workers 2
rem   run_per_symbol_optimizer.bat --universe all --systems BRT,RL --workers 4
rem   run_per_symbol_optimizer.bat --param-summary-only
rem   run_per_symbol_optimizer.bat --wf-mode rolling --systems RL --symbols TSLA --workers 1
rem   run_per_symbol_optimizer.bat --systems MTS --wf-mode rolling --optimize-mode universe --workers 2
rem   run_per_symbol_optimizer.bat --systems RL --wf-mode rolling --optimize-mode hierarchical --workers 5
rem   (hierarchical step 1 runs universe WF in parallel up to --workers; fold progress logged)
rem Production uses Per_Symbol_Optimized_Settings_Approved_Latest.json (ADOPT only)
setlocal EnableExtensions
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1
"%PY%" "%~dp0stock_analysis\per_symbol_optimizer.py" %*
exit /b %errorlevel%
