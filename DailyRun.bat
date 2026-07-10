@echo off

setlocal EnableExtensions

rem --- Project root (batch always cds here; Task Scheduler "Start in" is optional) ---
cd /d "C:\Users\songg\Downloads\stockresearch"

rem --- Shared RL/BRT symbol lists (daily_run_env.bat); override before calling if needed ---
call "%~dp0daily_run_env.bat"

rem --- Log file (one per run) ---
set "LOGDIR=%~dp0logs"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "STAMP=%%i"
set "LOG=%LOGDIR%\DailyRun_%STAMP%.log"

echo ============================================================>>"%LOG%"
echo DailyRun started: %date% %time%>>"%LOG%"
echo CD=%CD%>>"%LOG%"
echo USER=%USERNAME% COMPUTER=%COMPUTERNAME% SESSION=%SESSIONNAME%>>"%LOG%"

rem --- Python: prefer python.org (%%LOCALAPPDATA%%\Programs\Python\...) ---
rem     Microsoft Store / WindowsApps Python often returns "Access is denied" when
rem     Task Scheduler runs at 7pm (locked screen or non-interactive token).
set "PY="
if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not defined PY for /f "tokens=2*" %%a in ('reg query "HKCU\Software\Python\PythonCore\3.10\InstallPath" /v ExecutablePath 2^>nul ^| find "ExecutablePath"') do set "PY=%%b"
if not defined PY set "PY=C:\Program Files\WindowsApps\PythonSoftwareFoundation.Python.3.10_3.10.3056.0_x64__qbz5n2kfra8p0\python3.10.exe"
if not exist "%PY%" if exist "C:\Program Files\WindowsApps\PythonSoftwareFoundation.Python.3.10_3.10.3056.0_x64__qbz5n2kfra8p0\python.exe" set "PY=C:\Program Files\WindowsApps\PythonSoftwareFoundation.Python.3.10_3.10.3056.0_x64__qbz5n2kfra8p0\python.exe"

:try_python
echo PY=%PY%>>"%LOG%"
if not exist "%PY%" (
  echo ERROR: Python not found. Install Python 3.10 from python.org or: winget install Python.Python.3.10>>"%LOG%"
  exit /b 1
)
"%PY%" --version >>"%LOG%" 2>&1
if not errorlevel 1 goto :python_ok
echo WARNING: Python failed at %PY%>>"%LOG%"
if /i "%PY%"=="%LOCALAPPDATA%\Programs\Python\Python310\python.exe" goto :python_fail
if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" (
  set "PY=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
  goto :try_python
)
:python_fail
echo ERROR: No working Python. Store/WindowsApps builds often fail under Task Scheduler.>>"%LOG%"
echo        Install: winget install -e --id Python.Python.3.10 --scope user>>"%LOG%"
exit /b 1

:python_ok
rem --- Same interpreter for run_audit.ps1 (rl_emit_brt_mirror.py) and all run_*.bat ---
set "PYTHON_EXE=%PY%"

rem --- Verify packages on this interpreter (fresh python.org installs have none) ---
"%PY%" -c "import pandas, yfinance, duckdb, numpy" >>"%LOG%" 2>&1
if errorlevel 1 (
  echo WARNING: Missing Python packages on %PY%>>"%LOG%"
  echo Running: "%PY%" -m pip install -r requirements.txt>>"%LOG%"
  "%PY%" -m pip install --upgrade pip >>"%LOG%" 2>&1
  "%PY%" -m pip install -r requirements.txt >>"%LOG%" 2>&1
  if errorlevel 1 (
    echo ERROR: pip install failed. Run manually:>>"%LOG%"
    echo   "%PY%" -m pip install -r requirements.txt>>"%LOG%"
    exit /b 1
  )
  "%PY%" -c "import pandas, yfinance, duckdb, numpy" >>"%LOG%" 2>&1
  if errorlevel 1 (
    echo ERROR: Python packages still missing after pip install.>>"%LOG%"
    exit /b 1
  )
  echo Python packages OK after pip install.>>"%LOG%"
)

rem --- 1) Update data ---
echo [1/9] run_update_data>>"%LOG%"
call "%~dp0run_update_data.bat" >>"%LOG%" 2>&1
if errorlevel 1 goto :fail

rem --- 2) Pre-warm indicator disk cache ---
echo [2/9] run_warm_indicator_cache>>"%LOG%"
call "%~dp0run_warm_indicator_cache.bat" >>"%LOG%" 2>&1
if errorlevel 1 goto :fail

rem --- 3a) Audit (legacy AWK Rocket Launcher) ---
echo [3/9] run_audit (AWK RL)>>"%LOG%"
call "%~dp0run_audit.bat" -AllowRegression -s "%RL_SYMBOLS%" >>"%LOG%" 2>&1
if errorlevel 1 goto :fail
for /f "usebackq delims=" %%a in ("drive\last_run_ts.txt") do set "RL_AWK_TS=%%a"
if not defined RL_AWK_TS (
  echo ERROR: drive\last_run_ts.txt missing after run_audit>>"%LOG%"
  goto :fail
)
echo [3/9] AWK RL timestamp: %RL_AWK_TS%>>"%LOG%"

rem --- 3b) Python Rocket Launcher ---
echo [3/9] run_rl>>"%LOG%"
call "%~dp0run_rl.bat" >>"%LOG%" 2>&1
if errorlevel 1 goto :fail
for /f "usebackq delims=" %%a in ("drive\last_run_ts.txt") do set "RL_PY_TS=%%a"
if not defined RL_PY_TS (
  echo ERROR: drive\last_run_ts.txt missing after run_rl>>"%LOG%"
  goto :fail
)
echo [3/9] Python RL timestamp: %RL_PY_TS%>>"%LOG%"

rem --- 3c) AWK vs Python RL output parity ---
echo [3/9] run_rl_compare>>"%LOG%"
call "%~dp0run_rl_compare.bat" %RL_AWK_TS% %RL_PY_TS% >>"%LOG%" 2>&1
if errorlevel 1 goto :fail

rem --- 4) BRT backtest ---
echo [4/9] run_brt>>"%LOG%"
call "%~dp0run_brt.bat" >>"%LOG%" 2>&1
if errorlevel 1 goto :fail

rem --- 5) IND indicator-only backtest (full universe) ---
echo [5/9] run_ind>>"%LOG%"
call "%~dp0run_ind.bat" >>"%LOG%" 2>&1
if errorlevel 1 goto :fail

rem --- 6) YH backtest ---
echo [6/9] run_yh>>"%LOG%"
call "%~dp0run_yh.bat" >>"%LOG%" 2>&1
if errorlevel 1 goto :fail

rem --- 7) MTS backtest ---
echo [7/9] run_mts>>"%LOG%"
call "%~dp0run_mts.bat" >>"%LOG%" 2>&1
if errorlevel 1 goto :fail

rem --- 8) Copy latest run outputs ---
echo [8/9] run_copy_latest>>"%LOG%"
call "%~dp0run_copy_latest.bat" >>"%LOG%" 2>&1
if errorlevel 1 goto :fail

rem --- 9a) Live stop/target for open positions ---
echo [9/9] run_gettarget>>"%LOG%"
call "%~dp0run_gettarget.bat" >>"%LOG%" 2>&1
if errorlevel 1 goto :fail

rem --- 9b) Investment report + GitHub Pages ---
echo [9/9] publish_github_pages>>"%LOG%"
call "%~dp0publish_github_pages.bat" --push >>"%LOG%" 2>&1
if errorlevel 1 goto :fail

echo DailyRun finished OK: %date% %time%>>"%LOG%"
echo Log: %LOG%
exit /b 0

:fail
echo DailyRun FAILED (errorlevel=%errorlevel%): %date% %time%>>"%LOG%"
echo Log: %LOG%
exit /b 1
