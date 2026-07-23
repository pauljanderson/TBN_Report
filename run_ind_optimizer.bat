@echo off
rem IND parameter optimizer — fresh reset, high concurrency (-w 1 -b 30).
rem Status/ETA: stock_analysis\IND_optimizer_status.txt
rem Watch: powershell -Command "Get-Content -Wait stock_analysis\IND_optimizer_status.txt"
setlocal EnableExtensions
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

if not exist "logs" mkdir logs
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyMMddHHmmss"') do set TS=%%I
set "LOG=logs\IND_Optimizer_%TS%.log"

echo [%date% %time%] Starting IND_Optimizer --reset -w 1 -b 30
echo Log: %LOG%
echo Status: stock_analysis\IND_optimizer_status.txt
echo Watch: powershell -NoProfile -Command "Get-Content -Wait '%~dp0stock_analysis\IND_optimizer_status.txt'"
"%PY%" -u stock_analysis\IND_Optimizer.py --reset -w 1 -b 30 > "%LOG%" 2>&1
echo [%date% %time%] Exit code %errorlevel%
exit /b %errorlevel%
