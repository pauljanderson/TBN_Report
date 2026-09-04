@echo off

rem Daily trendline + VZ charts for opens + scanner universe (DailyRun step 13c)

rem Skip: set SKIP_TRENDLINES=1

setlocal EnableExtensions

cd /d "%~dp0"



if /i "%SKIP_TRENDLINES%"=="1" (

  echo SKIPPED - trendlines_daily_publish ^(SKIP_TRENDLINES=1^)

  exit /b 0

)



set "PY="

if defined PYTHON_EXE set "PY=%PYTHON_EXE%"

if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"

if not defined PY set "PY=python"



"%PY%" tools\trendlines_daily_publish.py %*

exit /b %errorlevel%

