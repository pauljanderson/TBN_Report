@echo off
rem =============================================================================
rem RL / RS / SB × IND-style gate A/B
rem
rem What this does
rem   1) Runs CONTROL backtests for RL, RS, SB (default universes under
rem      drive\universes\*_universe.csv — does NOT force full CSV universe).
rem   2) Post-filters each Closed book by IND_DIFF >= X and a couple of easy
rem      IND companions, then writes a sortable HTML + CSV comparison.
rem   3) Optional LIVE RS arms: re-run RS with -v indicator_buy=both
rem      -v indicator_diff=X (engine overlay wired in rocket_tbn RS scan).
rem
rem Why post-filter is the default for RL / SB
rem   - RS Closed already stamps IND_DIFF (use_indicators=true).
rem   - RL Closed is AWK-style and does not stamp IND_* columns.
rem   - SB production runs with use_indicators=false / indicator_buy=off, so
rem     Closed lacks IND_DIFF unless enriched.
rem   - Live indicator_buy=both is NOT a native RL/SB entry overlay today.
rem     The summarizer attaches IND_DIFF at the trigger bar (session before
rem     fill) via brt_entry_indicators cache, then filters.
rem   - Post-filter does NOT re-simulate host cash / concurrency — compare
rem     avg PNL%% / win rate / trade count, not raw sum dollars alone.
rem
rem Gate definitions (see tools\summarize_rl_rs_sb_ind_gate_ab.py)
rem   control              full Closed book
rem   ind_diff_ge_0|5|7|10|12
rem                        trade-aligned IND_DIFF >= X at trigger
rem                        (IND production: indicator_diff=7 on run_ind.bat)
rem   ind_neutral_le_30    IND_ENTRY_NEUTRAL_N <= 30 (IND max_ind_entry_neutral_n)
rem   spy_ind_diff_ge_0    SPY_IND_DIFF >= 0 when column is populated
rem
rem Skipped (and why)
rem   min_ind_score        IND sets -2 but engine activates only when >0
rem   use_average_ind      needs universe-mean pre-pass (heavy)
rem   atr_target/atr_stop  exit schedule, not an entry DIFF gate
rem
rem Usage
rem   run_rl_rs_sb_ind_gate_ab.bat
rem   set IND_GATE_SMOKE=1 && run_rl_rs_sb_ind_gate_ab.bat
rem   set POSTFILTER_ONLY=1 && run_rl_rs_sb_ind_gate_ab.bat
rem   set LIVE_RS_ARMS=1 && run_rl_rs_sb_ind_gate_ab.bat
rem   set RUN_RL=0 && set RUN_RS=1 && set RUN_SB=0 && run_rl_rs_sb_ind_gate_ab.bat
rem
rem Symbol / universe overrides (per system; smoke uses these)
rem   set RL_SYMBOLS=AAPL,MSFT     or  set RL_UNIVERSE_CSV=path\to.csv
rem   set RS_SYMBOLS=...           or  set RS_UNIVERSE_CSV=...
rem   set SB_SYMBOLS=...           or  set SB_UNIVERSE_CSV=...
rem   set SYS_SYMBOLS=AAPL,NVDA    applies to any system without its own list
rem   IND_GATE_SMOKE=1             defaults SYS_SYMBOLS=AAPL,MSFT,NVDA if unset
rem
rem Output
rem   drive\paul_experiments\rl_rs_sb_ind_gate_ab\comparison.html
rem   drive\paul_experiments\rl_rs_sb_ind_gate_ab\comparison.csv
rem   drive\paul_experiments\rl_rs_sb_ind_gate_ab\README.md
rem   (optional live RS copies) ...\live_rs\<arm>\
rem =============================================================================

setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

if not defined OUT set "OUT=drive\paul_experiments\rl_rs_sb_ind_gate_ab"
if not defined RUN_RL set "RUN_RL=1"
if not defined RUN_RS set "RUN_RS=1"
if not defined RUN_SB set "RUN_SB=1"
if not defined POSTFILTER_ONLY set "POSTFILTER_ONLY=0"
if not defined LIVE_RS_ARMS set "LIVE_RS_ARMS=0"
if not defined WRITE_ENRICHED set "WRITE_ENRICHED=1"
if not defined IND_GATE_WORKERS set "IND_GATE_WORKERS=4"

if /i "%IND_GATE_SMOKE%"=="1" goto :smoke_on
if /i "%IND_GATE_SMOKE%"=="true" goto :smoke_on
if /i "%IND_GATE_SMOKE%"=="yes" goto :smoke_on
goto :smoke_done
:smoke_on
if not defined SYS_SYMBOLS set "SYS_SYMBOLS=AAPL,MSFT,NVDA"
echo [IND-GATE] SMOKE on — SYS_SYMBOLS=!SYS_SYMBOLS!
:smoke_done

rem Propagate shared SYS_SYMBOLS to systems that do not already override
if defined SYS_SYMBOLS (
  if not defined RL_SYMBOLS set "RL_SYMBOLS=%SYS_SYMBOLS%"
  if not defined RS_SYMBOLS set "RS_SYMBOLS=%SYS_SYMBOLS%"
  if not defined SB_SYMBOLS set "SB_SYMBOLS=%SYS_SYMBOLS%"
)

if not exist "%OUT%" mkdir "%OUT%"

echo.
echo === RL / RS / SB × IND gate A/B ===
echo OUT=%OUT%
echo POSTFILTER_ONLY=%POSTFILTER_ONLY%  LIVE_RS_ARMS=%LIVE_RS_ARMS%
echo RUN_RL=%RUN_RL% RUN_RS=%RUN_RS% RUN_SB=%RUN_SB%
echo RL_SYMBOLS=%RL_SYMBOLS%
echo RS_SYMBOLS=%RS_SYMBOLS%
echo SB_SYMBOLS=%SB_SYMBOLS%
echo.

set "FAIL_COUNT=0"
set "RL_CLOSED="
set "RS_CLOSED="
set "SB_CLOSED="

if /i "%POSTFILTER_ONLY%"=="1" goto :postfilter
if /i "%POSTFILTER_ONLY%"=="true" goto :postfilter
if /i "%POSTFILTER_ONLY%"=="yes" goto :postfilter
goto :run_controls

:run_controls
if /i not "%RUN_RL%"=="1" if /i not "%RUN_RL%"=="true" if /i not "%RUN_RL%"=="yes" goto :after_rl
echo.
echo ========== [RL control] ==========
call "%~dp0run_rl.bat"
if errorlevel 1 (
  echo WARN: RL control failed errorlevel=!ERRORLEVEL!
  set /a FAIL_COUNT+=1
)
for /f "delims=" %%F in ('dir /b /o-d "drive\RL_Closed_*.csv" 2^>nul') do (
  set "RL_CLOSED=drive\%%F"
  goto :after_rl
)
:after_rl

if /i not "%RUN_RS%"=="1" if /i not "%RUN_RS%"=="true" if /i not "%RUN_RS%"=="yes" goto :after_rs
echo.
echo ========== [RS control] ==========
call "%~dp0run_rs.bat"
if errorlevel 1 (
  echo WARN: RS control failed errorlevel=!ERRORLEVEL!
  set /a FAIL_COUNT+=1
)
for /f "delims=" %%F in ('dir /b /o-d "drive\RS_Closed_*.csv" 2^>nul') do (
  set "RS_CLOSED=drive\%%F"
  goto :after_rs
)
:after_rs

if /i not "%RUN_SB%"=="1" if /i not "%RUN_SB%"=="true" if /i not "%RUN_SB%"=="yes" goto :after_sb
echo.
echo ========== [SB control] ==========
call "%~dp0run_sb.bat"
if errorlevel 1 (
  echo WARN: SB control failed errorlevel=!ERRORLEVEL!
  set /a FAIL_COUNT+=1
)
for /f "delims=" %%F in ('dir /b /o-d "drive\SB_Closed_*.csv" 2^>nul') do (
  set "SB_CLOSED=drive\%%F"
  goto :after_sb
)
:after_sb

rem Optional live RS IND_DIFF overlay arms (engine: indicator_buy=both)
if /i "%LIVE_RS_ARMS%"=="1" goto :live_rs
if /i "%LIVE_RS_ARMS%"=="true" goto :live_rs
if /i "%LIVE_RS_ARMS%"=="yes" goto :live_rs
goto :postfilter

:live_rs
echo.
echo ========== [RS live IND_DIFF arms] ==========
if not defined RS_TARGET set "RS_TARGET=1.25"
if not defined RS_STOP set "RS_STOP=0.88"
if not defined RS_WORKERS set "RS_WORKERS=12"
set "LIVE_ROOT=%OUT%\live_rs"
if not exist "%LIVE_ROOT%" mkdir "%LIVE_ROOT%"
set "RS_BASE=-v rs_mode=true -v brt_zones=false -v yh_zones=false -v wpbr_zones=false -v rl_mode=false -v target_pct=%RS_TARGET% -v stop_pct=%RS_STOP% -v stop_pct_is_multiplier=true -v use_indicators=true -v rs_require_tc_strong=true -v growth_filter_enabled=false -v min_spy_compare_1y_at_trigger=0 -v atr_days=0 -v too_high_multiplier=0 -v rs_max_pct_below_52w_high=0 -v rs_spy_int_tc_not_weak=true -v symbol_reentry_cooldown_days=60"

call :live_rs_arm 00_control " -v indicator_buy=off"
call :live_rs_arm 01_ind_diff_ge_0 " -v indicator_buy=both -v indicator_diff=0"
call :live_rs_arm 02_ind_diff_ge_5 " -v indicator_buy=both -v indicator_diff=5"
call :live_rs_arm 03_ind_diff_ge_7 " -v indicator_buy=both -v indicator_diff=7"
call :live_rs_arm 04_ind_diff_ge_10 " -v indicator_buy=both -v indicator_diff=10"
call :live_rs_arm 05_ind_diff_ge_12 " -v indicator_buy=both -v indicator_diff=12"
goto :postfilter

:live_rs_arm
set "ARM=%~1"
set "EXTRA=%~2"
echo.
echo --- live RS !ARM! ---
if not exist "%LIVE_ROOT%\!ARM!" mkdir "%LIVE_ROOT%\!ARM!"
if defined RS_SYMBOLS (
  "%PY%" stock_analysis\rocket_tbn.py data\newdata\data -o drive -w %RS_WORKERS% --no-regression --aggressive --relative-strength %RS_BASE% !EXTRA! -s "!RS_SYMBOLS!"
) else (
  "%PY%" stock_analysis\rocket_tbn.py data\newdata\data -o drive -w %RS_WORKERS% --no-regression --aggressive --relative-strength %RS_BASE% !EXTRA!
)
if errorlevel 1 (
  echo WARN: live RS !ARM! failed
  set /a FAIL_COUNT+=1
)
set "AUD="
for /f "delims=" %%F in ('dir /b /o-d "drive\RS_Audit_Report_*.csv" 2^>nul') do (
  set "AUD=%%F"
  goto :live_rs_got_aud
)
:live_rs_got_aud
if not defined AUD goto :eof
set "STAMP="
for /f "tokens=4 delims=_" %%S in ("!AUD!") do set "STAMP=%%S"
set "STAMP=!STAMP:.csv=!"
if defined STAMP (
  copy /Y "drive\RS_*_!STAMP!.csv" "%LIVE_ROOT%\!ARM!\" >nul 2>&1
  echo stamp=!STAMP!> "%LIVE_ROOT%\!ARM!\STAMP.txt"
)
goto :eof

:postfilter
echo.
echo ========== Post-filter summary ==========
set "PY_ARGS=--root %OUT% --workers %IND_GATE_WORKERS%"
if /i "%WRITE_ENRICHED%"=="1" set "PY_ARGS=!PY_ARGS! --write-enriched"
if /i "%WRITE_ENRICHED%"=="true" set "PY_ARGS=!PY_ARGS! --write-enriched"
if defined RL_CLOSED set "PY_ARGS=!PY_ARGS! --rl-closed !RL_CLOSED!"
if defined RS_CLOSED set "PY_ARGS=!PY_ARGS! --rs-closed !RS_CLOSED!"
if defined SB_CLOSED set "PY_ARGS=!PY_ARGS! --sb-closed !SB_CLOSED!"

"%PY%" "%~dp0tools\summarize_rl_rs_sb_ind_gate_ab.py" !PY_ARGS!
if errorlevel 1 (
  echo ERROR: summarizer failed
  exit /b 1
)

echo.
echo Done. Open:
echo   %OUT%\comparison.html
echo   %OUT%\comparison.csv
if !FAIL_COUNT! gtr 0 (
  echo WARN: FAIL_COUNT=!FAIL_COUNT!
  exit /b 1
)
exit /b 0
