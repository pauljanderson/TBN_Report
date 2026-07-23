@echo off
rem Copy latest BRT/IND/YH/MTS/WPBR/RS/RL timestamped CSVs (including Summary) to *_LatestRun_* stable names
setlocal EnableExtensions
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\Copy-LatestRunOutputs.ps1" %*
exit /b %errorlevel%
