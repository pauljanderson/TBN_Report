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
rem     Options chain archive (yfinance snapshot; NOT a sleeve / not gold / not reconcile):
rem       Optional last step: call run_options_chain.bat — continues on Yahoo error.
rem       Skip: set SKIP_OPTIONS_CHAIN=1
rem       Standalone: run_options_chain.bat
rem       Freeze: drive\paul_experiments\options_chain_archive_20260917\BASELINE.md
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
echo [3/13] run_rl_compare>>"%LOG%"
call "%~dp0run_rl_compare.bat" %RL_AWK_TS% %RL_PY_TS% >>"%LOG%" 2>&1
if errorlevel 1 goto :fail

rem --- 4) BRT system backtest (Break and ReTest; TBN engine via run_brt.bat ??? rocket_tbn.py) ---
echo [4/13] run_brt>>"%LOG%"
call "%~dp0run_brt.bat" >>"%LOG%" 2>&1
if errorlevel 1 goto :fail

rem --- 5) DEPRECATED: IND indicator-only backtest (manual script retained) ---
echo [5/13] SKIPPED - run_ind (IND deprecated)>>"%LOG%"

rem --- 6) YH backtest ---
echo [6/13] run_yh>>"%LOG%"
call "%~dp0run_yh.bat" >>"%LOG%" 2>&1
if errorlevel 1 goto :fail

rem --- 7) MTS backtest ---
echo [7/13] run_mts>>"%LOG%"
call "%~dp0run_mts.bat" >>"%LOG%" 2>&1
if errorlevel 1 goto :fail

rem --- 8) WPBR backtest (Mag9; run_wpbr.bat: SC-on, stop 0.91, target 1.22, NO start_date; AMD out of WPBR) ---
echo [8/13] run_wpbr>>"%LOG%"
call "%~dp0run_wpbr.bat" >>"%LOG%" 2>&1
if errorlevel 1 goto :fail

rem --- 9) RS (Relative Strength: SPY_COMPARE>0 + TC Strong) ---
echo [9/13] run_rs>>"%LOG%"
call "%~dp0run_rs.bat" >>"%LOG%" 2>&1
if errorlevel 1 goto :fail

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
  call "%~dp0run_sb.bat" >>"%LOG%" 2>&1
  if errorlevel 1 goto :fail
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
  call "%~dp0run_vz.bat" >>"%LOG%" 2>&1
  if errorlevel 1 goto :fail
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
  call "%~dp0run_rsi.bat" >>"%LOG%" 2>&1
  if errorlevel 1 goto :fail
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
  call "%~dp0run_wrl.bat" >>"%LOG%" 2>&1
  if errorlevel 1 goto :fail
)

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

rem --- 13c) Trendline + VZ 6m charts + buy-low B score + holdings sells ---
rem Runs after getTarget so gettarget_positions.csv is current; before GitHub Pages publish.
rem Universe: gettarget helds/opens U live DailyRun Open/Watchlist/Scanner U SPY/APP extras
rem Live sleeves from tools\dailyrun_system_status.py DAILYRUN_REGISTRY (wired=True).
rem Missing charts are generated then scored — no silent NO CHART skip.
rem Holdings SELL = weekly support DOWN and/or close through support (inverse of buy-low B).
rem Skip: set SKIP_TRENDLINES=1
rem Output: drive\paul_studies\trendlines_opens_latest\charts\index.html
rem         drive\paul_studies\trendlines_opens_latest\buy_today.html
rem         drive\Trendlines_BuyToday_Latest.html + mobile_inbox\results\
if /i "%SKIP_TRENDLINES%"=="1" (
  echo [13/13] SKIPPED - run_trendlines_daily ^(SKIP_TRENDLINES=1^)
  echo [13/13] SKIPPED - run_trendlines_daily ^(SKIP_TRENDLINES=1^)>>"%LOG%"
) else (
  echo [13/13] run_trendlines_daily
  echo [13/13] run_trendlines_daily>>"%LOG%"
  call "%~dp0run_trendlines_daily.bat" >>"%LOG%" 2>&1
  if errorlevel 1 goto :fail
)

rem --- 13d) Trendline ToS (Thinkorswim) study generation (M/W/D fractal .ts files) ---
rem Runs right after 13c chart creation; writes .ts files to drive\paul_studies\trendlines_tos_YYYYMMDD\
rem and copies to drive\paul_studies\trendlines_opens_latest\studies\ (latest/stable location).
rem Skip: set SKIP_TRENDLINES_TOS=1  (SKIP_TRENDLINES=1 also implies skip)
if /i "%SKIP_TRENDLINES_TOS%"=="1" (
  echo [13/13] SKIPPED - run_trendlines_tos_daily ^(SKIP_TRENDLINES_TOS=1^)
  echo [13/13] SKIPPED - run_trendlines_tos_daily ^(SKIP_TRENDLINES_TOS=1^)>>"%LOG%"
) else if /i "%SKIP_TRENDLINES%"=="1" (
  echo [13/13] SKIPPED - run_trendlines_tos_daily ^(SKIP_TRENDLINES=1^)
  echo [13/13] SKIPPED - run_trendlines_tos_daily ^(SKIP_TRENDLINES=1^)>>"%LOG%"
) else (
  echo [13/13] run_trendlines_tos_daily
  echo [13/13] run_trendlines_tos_daily>>"%LOG%"
  call "%~dp0run_trendlines_tos_daily.bat" >>"%LOG%" 2>&1
  if errorlevel 1 goto :fail
)

rem --- 13b) Investment report + GitHub Pages ---
echo [13/13] publish_github_pages>>"%LOG%"
call "%~dp0publish_github_pages.bat" --push >>"%LOG%" 2>&1
if errorlevel 1 goto :fail

rem --- 14) Options chain archive (yfinance snapshot; archive only; NOT a sleeve)
rem Not gold. Not a scanner. Not reconcile / LatestRun / house pins.
rem Yahoo flake must not fail DailyRun — bat always exits 0; still continue on error.
rem Skip: set SKIP_OPTIONS_CHAIN=1
rem Freeze: drive\paul_experiments\options_chain_archive_20260917\BASELINE.md
if /i "%SKIP_OPTIONS_CHAIN%"=="1" (
  echo [14] SKIPPED - run_options_chain ^(SKIP_OPTIONS_CHAIN=1^)
  echo [14] SKIPPED - run_options_chain ^(SKIP_OPTIONS_CHAIN=1^)>>"%LOG%"
) else (
  echo [14] run_options_chain ^(archive only; continue on Yahoo error^)
  echo [14] run_options_chain ^(archive only; continue on Yahoo error^)>>"%LOG%"
  call "%~dp0run_options_chain.bat" >>"%LOG%" 2>&1
  if errorlevel 1 (
    echo [14] WARN - options chain archive failed; DailyRun continues>>"%LOG%"
    echo [14] WARN - options chain archive failed; DailyRun continues
  )
)

echo DailyRun finished OK: %date% %time%>>"%LOG%"
echo Log: %LOG%
exit /b 0

:fail
echo DailyRun FAILED (errorlevel=%errorlevel%): %date% %time%>>"%LOG%"
echo Log: %LOG%
exit /b 1
