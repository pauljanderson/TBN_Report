@echo off
rem Shared zone catalog → replay target/stop on Closed entries (research only).
rem Not a product "zone exit" mode. See drive\paul_experiments\zones_as_target_stop_ab\DECISION_LOG.md
setlocal EnableExtensions
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

rem Reuse catalog if present; only build when missing (force via --build-catalog).
if not exist "drive\paul_experiments\zone_catalog\zone_catalog_latest.csv" (
  "%PY%" tools\build_zone_catalog.py --from-closed RS,RL,SB --include-markten --jobs 6
  if errorlevel 1 exit /b %errorlevel%
)

rem Default: one-sided + both; RR off (pass --rr 2,3,4 to enable)
"%PY%" tools\run_zones_as_target_stop_ab.py --systems RS,RL,SB,BRT,YH,WPBR,MTS %*
exit /b %errorlevel%
