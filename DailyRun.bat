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
rem     SB (StockBee) step [10/13]: call run_sb.bat — default gold 56 from drive\universes\SB_universe.csv
rem       Same CLI as other run_??.bat: no args = CSV whitelist; run_sb.bat ALL = full universe
rem       Standalone same default: run_sb.bat   (no args)
rem     set SB_SYMBOLS=NVDA,TSLA  override gold list
rem     set SB_SYMBOLS=*          (or ALL / SB_ALL_CSV=1) = all data\newdata\data\*.csv (no -s)
rem     Prefer set "SB_SYMBOLS=*" — bare set SB_SYMBOLS=* && leaves a trailing space (bat trims)
rem     set SKIP_SB=1             skip StockBee step
rem     VZ (Volume Zone) step [10b/13]: call run_vz.bat — house univ drive\universes\VZ_universe.csv
rem       DailyRun official TBN sleeve 2026-09-07: Paul78.142 + EXIT_atr4_s025_r15_ts20
rem         (atr4=4% ATR floor at trigger close, NOT a 4-ATR stop; s025=zone.lo-0.25*ATR; r15=1.5R; ts20=20 bars).
rem         Operational adopt 2026-09-07: trigger-priced 4% replaced entry-priced 4% (HOLD AB;
rem         scanner-live identity — not KEEP/gold). Entry gate off.
rem       One position per symbol (DailyRun lock 2026-09-15): do not buy a name we already hold.
rem         Always on in rocket_vz.enrich_trade_rows — no flag re-enables pyramids.
rem         Regression baseline = VZ_LatestRun_* / VZ_house_last_run_ts.txt (not an old pyramid stamp).
rem       Not walk-forward gold. Skip: set SKIP_VZ=1
rem       Freeze note: drive\paul_experiments\vz_tbn_adopt_s025_paul78_20260907\
rem       ATR% at trigger adopt: drive\paul_experiments\vz_atr_trigger_adopt_20260907\
rem       Keep VZ_REQUIRE_HVN_OVERLAP=false (house freeze; do not default-on).
rem     RSI (Relative Strength Index) step [10c/13]: call run_rsi.bat
rem       House univ drive\universes\rsi_universe.csv (149 HighFIT/ISgood). Not RS (vs SPY).
rem       Freeze: ob=70 os=30 exit=70 max_trigger=60 min_atr%=2.93 ts=20 next_open
rem         rsi_roll_from_max=8 (EXIT: in-trade max RSI − RSI >= 8, next open)
rem         min_dist52=off (0). Do not pass 7.18 — that was a preference wire, now reverted.
rem       Preference-adopt / DailyRun sleeve — not walk-forward gold. Skip: set SKIP_RSI=1
rem       Adopt note: drive\paul_experiments\rsi_roll_ab_20260916\
rem       Prior ATR% adopt: drive\paul_experiments\rsi_atr293_dailyrun_20260916\
rem       Prior ATR5 adopt: drive\paul_experiments\rsi_atr5_dailyrun_20260914\
rem       Prior 7.18 dist wire (reverted): drive\paul_experiments\rsi_mindist52_718_20260916\
rem     WRL (Weekly Range / Swing) step [10d/13]: call run_wrl.bat
rem       House univ drive\universes\WRL_universe.csv (29 names, no add/drop).
rem       Freeze: WRL_TARGET_MODE=swing (EXIT_swing — 100% off at swing high;
rem         stop swing low; min-zone off; cooldown unset).
rem       Official 6-sys live-style sleeve (SB/RSI/VZ/MTS/RL/WRL). Not gold.
rem       Skip: set SKIP_WRL=1
rem       Adopt: drive\paul_experiments\wrl_dailyrund_6sys_20260922\
rem     MVCP (Minervini VCP) — RETIRED 2026-08-21 from DailyRun and active reporting.
rem       Not a DailyRun step (SKIP_MVCP removed). Standalone research only:
rem       run_mvcp.bat / run_minervini_vcp.bat (engine + historical Closed stamps kept).
rem       Evidence: drive\paul_experiments\mvcp_vs_sb_rl_yearly_20260811.html
rem     set SKIP_RECONCILE_GATE=1 skip frozen Closed gate
rem     set SKIP_GET=1            skip pygetallMore (run_update_data)
rem     set FORCE_GET=1           always run pygetallMore (override auto fresh skip)
rem     set SKIP_FUND_SCORECARD=1 skip fund scorecard refresh + PIT snapshot (step 1b)
rem     set FORCE_FUND_SCORECARD=1 ignore scorecard Yahoo TTL (full refresh)
rem     set FUND_SCORECARD_TTL_DAYS=7  Yahoo multiples TTL (default 7)
rem     Options chain archive is no longer part of DailyRun (was step [14], removed 2026-10-02).
rem       Run it on its own, at a different time of day: run_options_chain.bat
rem       Archive only (yfinance snapshot). Not a sleeve / not gold / not reconcile.
rem       Freeze: drive\paul_experiments\options_chain_archive_20260917\BASELINE.md
rem     DailyRun --noGet          same as SKIP_GET=1
rem     DailyRun --no-get         same as SKIP_GET=1
rem     Default (no flags): auto — skip step 1 when data is fresh (see tools/data_update_freshness.py)
rem DailyRun.bat -w 8 runs independent systems together and gives each engine 8 workers
rem   (--workers 8 is the same). Omit -w to keep each script's own worker count.
rem   At most 8 system engines at once. If CPU load is above 90%, the next start waits.

rem --- CLI flags (optional) ---
rem -w / --workers sets DAILYRUN_WORKERS for engines that already take -w.
rem Help, -h, and --dry-parse exit before any engine starts.
:parse_args
if "%~1"=="" goto args_done
if /i "%~1"=="/?" goto :usage
if /i "%~1"=="-h" goto :usage
if /i "%~1"=="--help" goto :usage
if /i "%~1"=="--dry-parse" (
  set "DAILYRUN_DRY_PARSE=1"
  shift
  goto parse_args
)
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
if /i "%~1"=="-w" goto :take_workers
if /i "%~1"=="--workers" goto :take_workers
echo Unknown DailyRun option: %~1
goto :usage_fail

:take_workers
shift
if "%~1"=="" (
  echo DailyRun -w needs a whole number. Example: DailyRun.bat -w 8
  exit /b 1
)
set "DAILYRUN_WORKERS=%~1"
echo %DAILYRUN_WORKERS%| findstr /r "^[0-9][0-9]*$" >nul
if errorlevel 1 (
  echo DailyRun -w expects a whole number of workers, got: %DAILYRUN_WORKERS%
  exit /b 1
)
shift
goto parse_args

:args_done
if /i "%DAILYRUN_DRY_PARSE%"=="1" (
  if defined DAILYRUN_WORKERS (
    echo DAILYRUN_WORKERS=!DAILYRUN_WORKERS!
  ) else (
    echo DAILYRUN_WORKERS=
  )
  if /i "!SKIP_GET!"=="1" (echo SKIP_GET=1) else (echo SKIP_GET=)
  exit /b 0
)
goto :run_body

:usage
echo Usage: DailyRun.bat [-w N^|--workers N] [--noGet^|--no-get]
echo   -w N runs independent systems together and gives each engine N workers.
echo   At most 8 system engines at once. If CPU load is above 90%%, the next start waits.
echo   Omit -w to keep each run_*.bat worker default. Systems with no worker flag are unchanged.
echo   No worker flag: audit, update_data, fund scorecard, rl_compare, copy_latest,
echo   reconcile, gettarget, trendlines, trendlines_tos, publish.
exit /b 0

:usage_fail
echo Usage: DailyRun.bat [-w N^|--workers N] [--noGet^|--no-get]
exit /b 1

:run_body
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
if defined DAILYRUN_WORKERS echo DAILYRUN_WORKERS=%DAILYRUN_WORKERS%>>"%LOG%"

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

rem --- DailyRun system status session (investment report RUN/SKIPPED/STALE banner) ---
rem New live sleeve: add run_*.bat step above AND add the prefix to
rem tools\dailyrun_system_status.py DAILYRUN_REGISTRY (+ REPORT_ORDER).
rem Convergence report and trendline universe read that registry — one add.
"%PY%" "%~dp0tools\dailyrun_system_status.py" --drive "%~dp0drive" begin --stamp "%STAMP%" >>"%LOG%" 2>&1

rem --- 1) Update data (pygetallMore via run_update_data) ---
rem Disable: set SKIP_GET=1  or  DailyRun --noGet / --no-get
rem Force:   set FORCE_GET=1
rem Default: auto fresh check (drive\data_update_last_ok.json from last pygetallMore)
rem Intraday 1m (yfinance → data\intraday\1m) — RESEARCH only; not wired here.
rem   Standalone: python tools\fetch_intraday_1m.py -s SPY,AAPL --lookback-days 5
rem   Docs: docs\INTRADAY_1M.md (and data\intraday\HOW_TO.md next to local files)
rem   Optional later: call behind SKIP_INTRADAY (after daily update; small univ first).
set "SKIP_GET_REASON="
if /i not "%SKIP_GET%"=="1" if /i not "%FORCE_GET%"=="1" (
  echo [1/13] checking data freshness...
  echo [1/13] checking data freshness...>>"%LOG%"
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
    echo [1/13] SKIPPED - run_update_data / pygetallMore ^(data fresh — auto^)
    echo [1/13] SKIPPED - run_update_data / pygetallMore ^(data fresh — auto^)>>"%LOG%"
  ) else (
    echo [1/13] SKIPPED - run_update_data / pygetallMore ^(SKIP_GET=1^)
    echo [1/13] SKIPPED - run_update_data / pygetallMore ^(SKIP_GET=1^)>>"%LOG%"
  )
) else (
  echo [1/13] Data stale — running update>>"%LOG%"
  echo [1/13] run_update_data>>"%LOG%"
  call "%~dp0run_update_data.bat" >>"%LOG%" 2>&1
  if errorlevel 1 goto :fail
)

rem --- 1b) Fund scorecard refresh (TTL Yahoo) + dated PIT history snapshot ---
rem Runs even when step 1 auto-skips OHLC, so scores are not stuck on a stale cache.
rem Skip: set SKIP_FUND_SCORECARD=1
rem Force Yahoo: set FORCE_FUND_SCORECARD=1
rem Docs: drive\paul_experiments\fund_scorecard_pit_dailyrun_20260831\
if /i "%SKIP_FUND_SCORECARD%"=="1" (
  echo [1b/13] SKIPPED - run_fund_scorecard_refresh ^(SKIP_FUND_SCORECARD=1^)
  echo [1b/13] SKIPPED - run_fund_scorecard_refresh ^(SKIP_FUND_SCORECARD=1^)>>"%LOG%"
) else (
  echo [1b/13] run_fund_scorecard_refresh
  echo [1b/13] run_fund_scorecard_refresh>>"%LOG%"
  call "%~dp0run_fund_scorecard_refresh.bat" >>"%LOG%" 2>&1
  if errorlevel 1 goto :fail
  if not exist "%~dp0drive\fund_scorecard_latest\scores.csv" (
    echo [1b/13] WARN - fund_scorecard_latest\scores.csv missing after refresh>>"%LOG%"
  )
)

rem --- 2) Optional IND indicator cache warmup (WARM_IND=1) ---
rem Default OFF for most bats (use_indicators=false). RS always needs TC (use_indicators=true);
rem cold miss still builds on the fly. Set WARM_IND=1 before DailyRun to pre-warm the cache.
rem Manual one-liner: call run_warm_indicator_cache.bat
rem Cache is .brt_indicator_cache (INDICATOR_CACHE_VERSION=4); cold miss still builds TC on the fly.
if /i "%WARM_IND%"=="1" (
  echo [2/13] run_warm_indicator_cache ^(WARM_IND=1^)>>"%LOG%"
  call "%~dp0run_warm_indicator_cache.bat" >>"%LOG%" 2>&1
  if errorlevel 1 goto :fail
) else (
  echo [2/13] SKIPPED - run_warm_indicator_cache ^(set WARM_IND=1 to enable^)>>"%LOG%"
)

rem --- 3a) Audit (legacy AWK Rocket Launcher) ---
rem AWK audit has no -w / --workers flag. DAILYRUN_WORKERS is not passed here.
echo [3/13] run_audit (AWK RL)>>"%LOG%"
call "%~dp0run_audit.bat" -AllowRegression >>"%LOG%" 2>&1
if errorlevel 1 goto :fail
for /f "usebackq delims=" %%a in ("drive\last_run_ts.txt") do set "RL_AWK_TS=%%a"
if not defined RL_AWK_TS (
  echo ERROR: drive\last_run_ts.txt missing after run_audit>>"%LOG%"
  goto :fail
)
echo [3/13] AWK RL timestamp: %RL_AWK_TS%>>"%LOG%"

rem --- 3b) Python Rocket Launcher ---
echo [3/13] run_rl>>"%LOG%"
call "%~dp0run_rl.bat" >>"%LOG%" 2>&1
if errorlevel 1 goto :fail
for /f "usebackq delims=" %%a in ("drive\last_run_ts.txt") do set "RL_PY_TS=%%a"
if not defined RL_PY_TS (
  echo ERROR: drive\last_run_ts.txt missing after run_rl>>"%LOG%"
  goto :fail
)
echo [3/13] Python RL timestamp: %RL_PY_TS%>>"%LOG%"

rem --- 3c) AWK vs Python RL output parity ---
rem run_rl_compare has no worker flag.
echo [3/13] run_rl_compare>>"%LOG%"
call "%~dp0run_rl_compare.bat" %RL_AWK_TS% %RL_PY_TS% >>"%LOG%" 2>&1
if errorlevel 1 goto :fail

rem --- Wave: independent system runs (read warehouse, write their own PREFIX files) ---
rem Stay sequential before this: price download (writes ohlcv.duckdb), fund scorecard,
rem optional indicator warmup, AWK RL then Python RL then compare (shared RL files).
rem Stay sequential after: copy_latest, reconcile, gettarget, trendlines, publish.
rem YH and WPBR open data\ohlcv.duckdb read-only. Timing duckdb is per system
rem (TBN_INSTRUMENT_DB). Shared last_run_ts.txt is not written inside the wave.
rem Each wave engine already takes rocket_tbn -w. -w on DailyRun sets that count.
rem The wave starts at most 8 of these engines at once and does not kill a running one.
rem If CPU LoadPercentage is above 90, the next system waits and retries.
rem copy_latest, reconcile, gettarget, trendlines, and publish have no worker flag.
set "WAVEFILE=%TEMP%\DailyRun_wave_%STAMP%.txt"
if exist "%WAVEFILE%" del "%WAVEFILE%"

rem --- 4) BRT system backtest (Break and ReTest; TBN engine via run_brt.bat ??? rocket_tbn.py) ---
echo [4/13] run_brt>>"%LOG%"
echo 4/13;BRT;run_brt.bat;drive\BRT_profile.duckdb>>"%WAVEFILE%"

rem --- 5) DEPRECATED: IND indicator-only backtest (manual script retained) ---
echo [5/13] SKIPPED - run_ind (IND deprecated)>>"%LOG%"

rem --- 6) YH backtest ---
echo [6/13] run_yh>>"%LOG%"
echo 6/13;YH;run_yh.bat;drive\YH_profile.duckdb>>"%WAVEFILE%"

rem --- 7) MTS backtest ---
echo [7/13] run_mts>>"%LOG%"
echo 7/13;MTS;run_mts.bat;drive\MTS_profile.duckdb>>"%WAVEFILE%"

rem --- 8) WPBR backtest (full data directory; run_wpbr.bat freeze 2026-10-02:
rem     22%% overhead arm of wpbr_overhead20_vs22_t20s8_ab_20261002 stamp 261002051403;
rem     overhead 0.22, stop 0.92 under the trigger-day low, target 1.20,
rem     min_history_bars=0, growth filter off, NO start_date) ---
echo [8/13] run_wpbr ^(full data directory; overhead 22%%; target 1.20; stop 0.92; growth filter off^)>>"%LOG%"
echo 8/13;WPBR;run_wpbr.bat;drive\WPBR_profile.duckdb>>"%WAVEFILE%"

rem --- 9) RS (Relative Strength: SPY_COMPARE>0 + TC Strong) ---
echo [9/13] run_rs>>"%LOG%"
echo 9/13;RS;run_rs.bat;drive\RS_profile.duckdb>>"%WAVEFILE%"

rem --- 10) SB (StockBee Momentum Burst) -----------------------------------------
rem Default: run_sb.bat with no args loads drive\universes\SB_universe.csv (56 names)
rem Disable: set SKIP_SB=1
rem Docs: drive\paul_experiments\tbn_new_systems\stockbee_momentum_burst\HOW_TO_RUN.html
if /i "%SKIP_SB%"=="1" (
  echo [10/13] SKIPPED - run_sb ^(SKIP_SB=1^)
  echo [10/13] SKIPPED - run_sb ^(SKIP_SB=1^)>>"%LOG%"
  "%PY%" "%~dp0tools\dailyrun_system_status.py" --drive "%~dp0drive" set SB SKIPPED --reason "SKIP_SB=1" >>"%LOG%" 2>&1
) else (
  rem Loud WARN if console left full-universe overrides set (do not block)
  if /i "%SB_SYMBOLS%"=="*" (
    echo [10/13] WARN: SB_SYMBOLS=* - DailyRun SB will scan FULL data CSVs, not gold-56. Unset SB_SYMBOLS for production.
    echo [10/13] WARN: SB_SYMBOLS=* - DailyRun SB will scan FULL data CSVs, not gold-56. Unset SB_SYMBOLS for production.>>"%LOG%"
  )
  if /i "%SB_SYMBOLS%"=="ALL" (
    echo [10/13] WARN: SB_SYMBOLS=ALL - DailyRun SB will scan FULL data CSVs, not gold-56. Unset SB_SYMBOLS for production.
    echo [10/13] WARN: SB_SYMBOLS=ALL - DailyRun SB will scan FULL data CSVs, not gold-56. Unset SB_SYMBOLS for production.>>"%LOG%"
  )
  if "%SB_ALL_CSV%"=="1" (
    echo [10/13] WARN: SB_ALL_CSV=1 - DailyRun SB will scan FULL data CSVs, not gold-56. Unset SB_ALL_CSV for production.
    echo [10/13] WARN: SB_ALL_CSV=1 - DailyRun SB will scan FULL data CSVs, not gold-56. Unset SB_ALL_CSV for production.>>"%LOG%"
  )
  echo [10/13] run_sb ^(gold SB_universe.csv^)
  echo [10/13] run_sb ^(gold SB_universe.csv^)>>"%LOG%"
  echo 10/13;SB;run_sb.bat;drive\SB_profile.duckdb>>"!WAVEFILE!"
)

rem --- 10b) VZ (Volume Zone) ----------------------------------------------------
rem Default: run_vz.bat with no args loads drive\universes\VZ_universe.csv (Paul78.142, 142-name house)
rem Combined freeze: exit_bars=20 (ts20), stop atr 0.25 (EXIT_atr4_s025_r15_ts20;
rem   atr4=4% ATR floor at trigger close, not a 4-ATR stop; entry gate off)
rem One position per symbol (DailyRun lock 2026-09-15): skip a later signal while still held.
rem   Always on — no env flag re-enables pyramids. LatestRun / house pin = regression baseline.
rem Disable: set SKIP_VZ=1
if /i "%SKIP_VZ%"=="1" (
  echo [10b/13] SKIPPED - run_vz ^(SKIP_VZ=1^)
  echo [10b/13] SKIPPED - run_vz ^(SKIP_VZ=1^)>>"%LOG%"
  "%PY%" "%~dp0tools\dailyrun_system_status.py" --drive "%~dp0drive" set VZ SKIPPED --reason "SKIP_VZ=1" >>"%LOG%" 2>&1
) else (
  echo [10b/13] run_vz ^(house VZ_universe.csv; exit_bars=20 stop_atr=0.25; one position per symbol^)
  echo [10b/13] run_vz ^(house VZ_universe.csv; exit_bars=20 stop_atr=0.25; one position per symbol^)>>"%LOG%"
  echo 10b/13;VZ;run_vz.bat;drive\VZ_profile.duckdb>>"!WAVEFILE!"
)

rem --- 10c) RSI (Relative Strength Index) ----------------
rem Default: run_rsi.bat loads drive\universes\rsi_universe.csv (149-name house)
rem Freeze: rsi_ob=70 rsi_os=30 rsi_exit=70 max_trigger=60 min_atr%=2.93 ts=20 roll_from_max=8 next_open min_dist52=off
rem Not RS (Relative Strength vs SPY). Disable: set SKIP_RSI=1
if /i "%SKIP_RSI%"=="1" (
  echo [10c/13] SKIPPED - run_rsi ^(SKIP_RSI=1^)
  echo [10c/13] SKIPPED - run_rsi ^(SKIP_RSI=1^)>>"%LOG%"
  "%PY%" "%~dp0tools\dailyrun_system_status.py" --drive "%~dp0drive" set RSI SKIPPED --reason "SKIP_RSI=1" >>"%LOG%" 2>&1
) else (
  echo [10c/13] run_rsi ^(house rsi_universe.csv; ob70/exit70/maxrsi60/atr2.93/ts20/roll8/min_dist52=off^)
  echo [10c/13] run_rsi ^(house rsi_universe.csv; ob70/exit70/maxrsi60/atr2.93/ts20/roll8/min_dist52=off^)>>"%LOG%"
  echo 10c/13;RSI;run_rsi.bat;drive\RSI_profile.duckdb>>"!WAVEFILE!"
)

rem --- 10d) WRL (Weekly Range / Swing) --------------------------------
rem Default: run_wrl.bat loads drive\universes\WRL_universe.csv (29-name house)
rem Freeze: WRL_TARGET_MODE=swing (EXIT_swing; stop swing low; min-zone off)
rem Official 6-sys sleeve — not gold. Disable: set SKIP_WRL=1
if /i "%SKIP_WRL%"=="1" (
  echo [10d/13] SKIPPED - run_wrl ^(SKIP_WRL=1^)
  echo [10d/13] SKIPPED - run_wrl ^(SKIP_WRL=1^)>>"%LOG%"
  "%PY%" "%~dp0tools\dailyrun_system_status.py" --drive "%~dp0drive" set WRL SKIPPED --reason "SKIP_WRL=1" >>"%LOG%" 2>&1
) else (
  echo [10d/13] run_wrl ^(house WRL_universe.csv; TARGET_MODE=swing; EXIT_swing 29-name^)
  echo [10d/13] run_wrl ^(house WRL_universe.csv; TARGET_MODE=swing; EXIT_swing 29-name^)>>"%LOG%"
  set "WRL_TARGET_MODE=swing"
  echo 10d/13;WRL;run_wrl.bat;drive\WRL_profile.duckdb>>"!WAVEFILE!"
)

echo [wave] independent systems, at most 8 at once ^(BRT YH MTS WPBR RS and any of SB VZ RSI WRL not skipped^)
echo [wave] independent systems, at most 8 at once>>"%LOG%"
"%PY%" "%~dp0tools\dailyrun_wave.py" --log "%LOG%" --jobs-file "%WAVEFILE%"
if errorlevel 1 goto :fail
del "%WAVEFILE%" 2>nul

rem --- Status snapshot (RUN / SKIPPED / NOT WIRED) before LatestRun promotion ---
"%PY%" "%~dp0tools\dailyrun_system_status.py" --drive "%~dp0drive" finalize >>"%LOG%" 2>&1

rem --- 11) Copy latest run outputs ---
echo [11/13] run_copy_latest>>"%LOG%"
call "%~dp0run_copy_latest.bat" >>"%LOG%" 2>&1
if errorlevel 1 goto :fail

rem --- 12) Reconcile gate (frozen engine Closed vs latest; YH/BRT/WPBR/RS/SB/RL/VZ; MVCP retired)
rem Disable: set SKIP_RECONCILE_GATE=1  or  set RECONCILE_GATE=0
rem Docs: drive\paul_experiments\yh_baseline_20260731\RECONCILE_GATE.md
echo [12/13] run_reconcile_gate>>"%LOG%"
call "%~dp0run_reconcile_gate.bat" >>"%LOG%" 2>&1
if errorlevel 1 goto :fail

rem --- 13a) Live stop/target for open positions ---
echo [13/13] run_gettarget>>"%LOG%"
call "%~dp0run_gettarget.bat" >>"%LOG%" 2>&1
if errorlevel 1 goto :fail

rem --- 14b) Investment report + GitHub Pages ---
rem --push fetches/rebases origin/main first so a long DailyRun does not fail if main moved.
echo [14/14] publish_github_pages>>"%LOG%"
call "%~dp0publish_github_pages.bat" --push >>"%LOG%" 2>&1
if errorlevel 1 goto :fail

rem --- Options chain archive is no longer part of DailyRun (was step [14]).
rem Run at a different time of day: run_options_chain.bat

echo DailyRun finished OK: %date% %time%>>"%LOG%"
echo Log: %LOG%
exit /b 0

:fail
echo DailyRun FAILED (errorlevel=%errorlevel%): %date% %time%>>"%LOG%"
echo Log: %LOG%
exit /b 1
