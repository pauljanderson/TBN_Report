@echo off

setlocal EnableExtensions EnableDelayedExpansion

rem --- Project root (batch always cds here; Task Scheduler "Start in" is optional) ---
cd /d "C:\Users\songg\Downloads\stockresearch"

rem --- Each run_*.bat owns its default symbol list (standalone). Override before calling, e.g.:
rem     set BRT_SYMBOLS=AAPL,MSFT
rem     set RL_SYMBOLS=AMD,NFLX  (default universe lives in run_rl.bat / run_audit.bat)
rem     set RS_SYMBOLS=NVDA,AVGO
rem     set RS_TARGET=1.21
rem     set RS_STOP=0.934
rem     SB (StockBee) step [10/14]: call run_sb.bat — default gold 56 from drive\universes\SB_universe.csv
rem       Same CLI as other run_??.bat: no args = CSV whitelist; run_sb.bat ALL = full universe
rem       Standalone same default: run_sb.bat   (no args)
rem     set SB_SYMBOLS=NVDA,TSLA  override gold list
rem     set SB_SYMBOLS=*          (or ALL / SB_ALL_CSV=1) = all data\newdata\data\*.csv (no -s)
rem     Prefer set "SB_SYMBOLS=*" — bare set SB_SYMBOLS=* && leaves a trailing space (bat trims)
rem     set SKIP_SB=1             skip StockBee step
rem     VZ (Volume Zone) — RESEARCH sleeve only; NOT in DailyRun step list.
rem       Standalone: run_vz.bat  (drive\universes\VZ_universe.csv DualPaul78 research default)
rem       Optional later: call run_vz.bat behind SKIP_VZ — do not treat as gold from wiring alone.
rem     WRL (Weekly Range / Swing) — RESEARCH sleeve; runner lives at this root:
rem       C:\Users\songg\Downloads\stockresearch\run_wrl.bat
rem       Standalone: run_wrl.bat  (Mag10 default; run_wrl.bat ALL = full universe)
rem       Optional later: call run_wrl.bat behind SKIP_WRL — do not treat as gold from wiring alone.
rem     MVCP (Minervini VCP) — PARKED 2026-08-12 from live DailyRun sleeve (research only).
rem       Evidence: drive\paul_experiments\mvcp_vs_sb_rl_yearly_20260811.html / PARK.md
rem       Standalone research: run_mvcp.bat / run_minervini_vcp.bat (engine kept).
rem       Default: SKIP_MVCP=1. Opt-in only: set SKIP_MVCP=0
rem       set MVCP_SYMBOLS=NVDA,TSLA  override ALL scan when opting in
rem     set SKIP_RECONCILE_GATE=1 skip frozen Closed gate
rem     set SKIP_GET=1            skip pygetallMore (run_update_data)
rem     set FORCE_GET=1           always run pygetallMore (override auto fresh skip)
rem     DailyRun --noGet          same as SKIP_GET=1
rem     DailyRun --no-get         same as SKIP_GET=1
rem     Default (no flags): auto — skip step 1 when data is fresh (see tools/data_update_freshness.py)

rem --- CLI flags (optional) ---
:parse_args
if "%~1"=="" goto args_done
if /i "%~1"=="--noGet" (
  set "SKIP_GET=1"
  shift
  goto parse_args
)
if /i "%~1"=="--no-get" (
  set "SKIP_GET=1"
  shift
  goto parse_args
)
echo Unknown DailyRun option: %~1
echo Usage: DailyRun [--noGet^|--no-get]
echo   or:  set SKIP_GET=1 ^& DailyRun
exit /b 1
:args_done

rem --- Log file (one per run) ---
set "LOGDIR=%~dp0logs"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
if not exist "%~dp0drive" mkdir "%~dp0drive"

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

rem --- 1) Update data (pygetallMore via run_update_data) ---
rem Disable: set SKIP_GET=1  or  DailyRun --noGet / --no-get
rem Force:   set FORCE_GET=1
rem Default: auto fresh check (drive\data_update_last_ok.json from last pygetallMore)
set "SKIP_GET_REASON="
if /i not "%SKIP_GET%"=="1" if /i not "%FORCE_GET%"=="1" (
  echo [1/14] checking data freshness...
  echo [1/14] checking data freshness...>>"%LOG%"
  set "FRESHCHK=%TEMP%\DailyRun_fresh_%STAMP%.txt"
  "%PY%" tools\data_update_freshness.py --check > "!FRESHCHK!" 2>&1
  set "FRESH_EXIT=!errorlevel!"
  type "!FRESHCHK!"
  type "!FRESHCHK!">>"%LOG%"
  if "!FRESH_EXIT!"=="0" (
    set "SKIP_GET=1"
    set "SKIP_GET_REASON=auto"
  )
  del "!FRESHCHK!" 2>nul
)
if /i "%SKIP_GET%"=="1" (
  if /i "%SKIP_GET_REASON%"=="auto" (
    echo [1/14] SKIPPED - run_update_data / pygetallMore ^(data fresh — auto^)
    echo [1/14] SKIPPED - run_update_data / pygetallMore ^(data fresh — auto^)>>"%LOG%"
  ) else (
    echo [1/14] SKIPPED - run_update_data / pygetallMore ^(SKIP_GET=1^)
    echo [1/14] SKIPPED - run_update_data / pygetallMore ^(SKIP_GET=1^)>>"%LOG%"
  )
) else (
  echo [1/14] Data stale — running update>>"%LOG%"
  echo [1/14] run_update_data>>"%LOG%"
  call "%~dp0run_update_data.bat" >>"%LOG%" 2>&1
  if errorlevel 1 goto :fail
)

rem --- 2) Optional IND indicator cache warmup (WARM_IND=1) ---
rem Default OFF for most bats (use_indicators=false). RS always needs TC (use_indicators=true);
rem cold miss still builds on the fly. Set WARM_IND=1 before DailyRun to pre-warm the cache.
rem Manual one-liner: call run_warm_indicator_cache.bat
rem Cache is .brt_indicator_cache (INDICATOR_CACHE_VERSION=4); cold miss still builds TC on the fly.
if /i "%WARM_IND%"=="1" (
  echo [2/14] run_warm_indicator_cache ^(WARM_IND=1^)>>"%LOG%"
  call "%~dp0run_warm_indicator_cache.bat" >>"%LOG%" 2>&1
  if errorlevel 1 goto :fail
) else (
  echo [2/14] SKIPPED - run_warm_indicator_cache ^(set WARM_IND=1 to enable^)>>"%LOG%"
)

rem --- 3a) Audit (legacy AWK Rocket Launcher) ---
echo [3/14] run_audit (AWK RL)>>"%LOG%"
call "%~dp0run_audit.bat" -AllowRegression >>"%LOG%" 2>&1
if errorlevel 1 goto :fail
for /f "usebackq delims=" %%a in ("drive\last_run_ts.txt") do set "RL_AWK_TS=%%a"
if not defined RL_AWK_TS (
  echo ERROR: drive\last_run_ts.txt missing after run_audit>>"%LOG%"
  goto :fail
)
echo [3/14] AWK RL timestamp: %RL_AWK_TS%>>"%LOG%"

rem --- 3b) Python Rocket Launcher ---
echo [3/14] run_rl>>"%LOG%"
call "%~dp0run_rl.bat" >>"%LOG%" 2>&1
if errorlevel 1 goto :fail
for /f "usebackq delims=" %%a in ("drive\last_run_ts.txt") do set "RL_PY_TS=%%a"
if not defined RL_PY_TS (
  echo ERROR: drive\last_run_ts.txt missing after run_rl>>"%LOG%"
  goto :fail
)
echo [3/14] Python RL timestamp: %RL_PY_TS%>>"%LOG%"

rem --- 3c) AWK vs Python RL output parity ---
echo [3/14] run_rl_compare>>"%LOG%"
call "%~dp0run_rl_compare.bat" %RL_AWK_TS% %RL_PY_TS% >>"%LOG%" 2>&1
if errorlevel 1 goto :fail

rem --- 4) BRT system backtest (Break and ReTest; TBN engine via run_brt.bat ??? rocket_tbn.py) ---
echo [4/14] run_brt>>"%LOG%"
call "%~dp0run_brt.bat" >>"%LOG%" 2>&1
if errorlevel 1 goto :fail

rem --- 5) DEPRECATED: IND indicator-only backtest (manual script retained) ---
echo [5/14] SKIPPED - run_ind (IND deprecated)>>"%LOG%"

rem --- 6) YH backtest ---
echo [6/14] run_yh>>"%LOG%"
call "%~dp0run_yh.bat" >>"%LOG%" 2>&1
if errorlevel 1 goto :fail

rem --- 7) MTS backtest ---
echo [7/14] run_mts>>"%LOG%"
call "%~dp0run_mts.bat" >>"%LOG%" 2>&1
if errorlevel 1 goto :fail

rem --- 8) WPBR backtest (Mag9; run_wpbr.bat: SC-on, stop 0.91, target 1.22, NO start_date; AMD out of WPBR) ---
echo [8/14] run_wpbr>>"%LOG%"
call "%~dp0run_wpbr.bat" >>"%LOG%" 2>&1
if errorlevel 1 goto :fail

rem --- 9) RS (Relative Strength: SPY_COMPARE>0 + TC Strong) ---
echo [9/14] run_rs>>"%LOG%"
call "%~dp0run_rs.bat" >>"%LOG%" 2>&1
if errorlevel 1 goto :fail

rem --- 10) SB (StockBee Momentum Burst) -----------------------------------------
rem Default: run_sb.bat with no args loads drive\universes\SB_universe.csv (56 names)
rem Disable: set SKIP_SB=1
rem Docs: drive\paul_experiments\tbn_new_systems\stockbee_momentum_burst\HOW_TO_RUN.html
if /i "%SKIP_SB%"=="1" (
  echo [10/14] SKIPPED - run_sb ^(SKIP_SB=1^)
  echo [10/14] SKIPPED - run_sb ^(SKIP_SB=1^)>>"%LOG%"
) else (
  rem Loud WARN if console left full-universe overrides set (do not block)
  if /i "%SB_SYMBOLS%"=="*" (
    echo [10/14] WARN: SB_SYMBOLS=* - DailyRun SB will scan FULL data CSVs, not gold-56. Unset SB_SYMBOLS for production.
    echo [10/14] WARN: SB_SYMBOLS=* - DailyRun SB will scan FULL data CSVs, not gold-56. Unset SB_SYMBOLS for production.>>"%LOG%"
  )
  if /i "%SB_SYMBOLS%"=="ALL" (
    echo [10/14] WARN: SB_SYMBOLS=ALL - DailyRun SB will scan FULL data CSVs, not gold-56. Unset SB_SYMBOLS for production.
    echo [10/14] WARN: SB_SYMBOLS=ALL - DailyRun SB will scan FULL data CSVs, not gold-56. Unset SB_SYMBOLS for production.>>"%LOG%"
  )
  if "%SB_ALL_CSV%"=="1" (
    echo [10/14] WARN: SB_ALL_CSV=1 - DailyRun SB will scan FULL data CSVs, not gold-56. Unset SB_ALL_CSV for production.
    echo [10/14] WARN: SB_ALL_CSV=1 - DailyRun SB will scan FULL data CSVs, not gold-56. Unset SB_ALL_CSV for production.>>"%LOG%"
  )
  echo [10/14] run_sb ^(gold SB_universe.csv^)
  echo [10/14] run_sb ^(gold SB_universe.csv^)>>"%LOG%"
  call "%~dp0run_sb.bat" >>"%LOG%" 2>&1
  if errorlevel 1 goto :fail
)

rem --- 11) MVCP (PARKED — research only; not live sleeve) -----------------------
rem PARK 2026-08-12: default skip so MVCP does not drag DailyRun / allocation.
rem Opt-in: set SKIP_MVCP=0  then this step calls run_mvcp.bat
rem Docs: drive\paul_experiments\mvcp_vs_sb_rl_yearly_20260811.html / PARK.md
if not defined SKIP_MVCP set "SKIP_MVCP=1"
if /i not "%SKIP_MVCP%"=="0" (
  echo [11/14] PARKED - run_mvcp ^(SKIP_MVCP=%SKIP_MVCP%; set SKIP_MVCP=0 to opt in^)
  echo [11/14] PARKED - run_mvcp ^(SKIP_MVCP=%SKIP_MVCP%^)>>"%LOG%"
) else (
  echo [11/14] run_mvcp ^(opt-in SKIP_MVCP=0 / MVCP_universe.csv^)
  echo [11/14] run_mvcp ^(opt-in SKIP_MVCP=0 / MVCP_universe.csv^)>>"%LOG%"
  call "%~dp0run_mvcp.bat" >>"%LOG%" 2>&1
  if errorlevel 1 goto :fail
)

rem --- 12) Copy latest run outputs ---
echo [12/14] run_copy_latest>>"%LOG%"
call "%~dp0run_copy_latest.bat" >>"%LOG%" 2>&1
if errorlevel 1 goto :fail

rem --- 13) Reconcile gate (frozen engine Closed vs latest; YH/BRT/WPBR/RS/SB; MVCP parked)
rem Disable: set SKIP_RECONCILE_GATE=1  or  set RECONCILE_GATE=0
rem Docs: drive\paul_experiments\yh_baseline_20260731\RECONCILE_GATE.md
echo [13/14] run_reconcile_gate>>"%LOG%"
call "%~dp0run_reconcile_gate.bat" >>"%LOG%" 2>&1
if errorlevel 1 goto :fail

rem --- 14a) Live stop/target for open positions ---
echo [14/14] run_gettarget>>"%LOG%"
call "%~dp0run_gettarget.bat" >>"%LOG%" 2>&1
if errorlevel 1 goto :fail

rem --- 14b) Investment report + GitHub Pages ---
rem --push fetches/rebases origin/main first so a long DailyRun does not fail if main moved.
echo [14/14] publish_github_pages>>"%LOG%"
call "%~dp0publish_github_pages.bat" --push >>"%LOG%" 2>&1
if errorlevel 1 goto :fail

echo DailyRun finished OK: %date% %time%>>"%LOG%"
echo Log: %LOG%
exit /b 0

:fail
echo DailyRun FAILED (errorlevel=%errorlevel%): %date% %time%>>"%LOG%"
echo Log: %LOG%
exit /b 1
