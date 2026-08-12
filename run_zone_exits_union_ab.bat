@echo off
rem Zone exits union A/B: static vs own-zone vs union DNA target/stop (+ RR 2/3/4).
rem   run_zone_exits_union_ab.bat
rem   run_zone_exits_union_ab.bat --systems BRT,YH --jobs 2
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1
"%PY%" tools\run_zone_exits_union_ab.py %*
exit /b %errorlevel%
