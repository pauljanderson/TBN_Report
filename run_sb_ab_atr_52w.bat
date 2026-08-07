@echo off
rem StockBee Momentum Burst A/B: ATR%% + DIST_TO_52W_HIGH gates at trigger.
rem Does NOT change production run_sb.bat / run_stockbee_burst.bat defaults.
rem Root alias: SB_ATR_52w_ab.bat (preferred one-liner for custom universe).
rem
rem EDIT SETTINGS: change ATR_MIN / DIST52_MIN (and optional rem lines) in the
rem   "EDIT DEFAULTS HERE" block below — save, then run. Env override still works
rem   if already set (same pattern as run_BRT.bat / run_stockbee_burst.bat).
rem
rem Gold Closed analysis (stamp 260802090646):
rem   ATR_PCT_AT_TRIGGER  — higher ATR%% correlates with higher avg PnL%%
rem                         default ATR_MIN=3.02 (median)
rem   DIST_TO_52W_HIGH_PCT_AT_TRIGGER — %% below 52w high (0=at high, larger=further)
rem                         data: FURTHER from highs has higher avg PnL%%
rem                         default DIST52_MIN=13.2 (median)
rem   (Closer-to-high / max_dist offline filter HURT avg PnL%% — not used in arms.)
rem
rem Arms (thresholds = ATR_MIN / DIST52_MIN from settings block):
rem   00_control         — gold defaults, both gates off
rem   01_atr_only        — burst_min_atr_pct_at_trigger=ATR_MIN
rem   02_dist52_only     — burst_min_dist_to_52w_high_pct=DIST52_MIN
rem   03_atr_and_dist52  — both
rem
rem Universe (first match wins):
rem   -s / --symbol LIST   e.g. SB_ATR_52w_ab.bat -s HROW,REAL,AKR
rem                        or  SB_ATR_52w_ab.bat -s "HROW,REAL,AKR"
rem   %%1 comma list       e.g. SB_ATR_52w_ab.bat HROW,REAL,AKR
rem                        (quote the list if it has commas: "HROW,REAL,AKR")
rem   %%1 path to GOLD-style csv (one line of tickers)
rem   SB_SYMBOLS env       (or uncomment set in settings block)
rem   else GOLD_UNIVERSE.csv
rem
rem How to run:
rem   SB_ATR_52w_ab.bat
rem   SB_ATR_52w_ab.bat HROW,REAL,AKR
rem   SB_ATR_52w_ab.bat -s HROW,REAL,AKR
rem   SB_ATR_52w_ab.bat -s "HROW,REAL,AKR"
rem   run_sb_ab_atr_52w.bat
rem   (optional) set SB_ATR_SMOKE=1  — run 00_control only (quoting/stamp check)
rem   (optional) set SB_ATR_RESOLVE_ONLY=1 — universe + Gates echo, no arms
rem
rem Output:
rem   - Primary: drive\SB_*_<stamp>.csv
rem   - Copies:  drive\paul_experiments\tbn_new_systems\stockbee_momentum_burst\ab_atr_52w\<arm>\
rem After suite: tools\summarize_sb_atr_52w_ab.py writes HTML+MD comparison.
rem
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

rem === EDIT DEFAULTS HERE (open this file, change values, save, run) ===
rem Env already set before call still wins (if not defined). Example: ATR_MIN=2.5 DIST52_MIN=10
if not defined ATR_MIN set "ATR_MIN=3.4"
if not defined DIST52_MIN set "DIST52_MIN=13.12"
if not defined SB_WORKERS set "SB_WORKERS=0"
if not defined SB_AGGRESSIVE set "SB_AGGRESSIVE=true"
rem if not defined SB_SYMBOLS set "SB_SYMBOLS=HROW,REAL,AKR"
rem === end defaults ===

set "DRIVE_OUT=drive"
set "OUT=drive\paul_experiments\tbn_new_systems\stockbee_momentum_burst\ab_atr_52w"
set "GOLD=%~dp0drive\paul_experiments\tbn_new_systems\stockbee_momentum_burst\GOLD_UNIVERSE.csv"

rem --- Universe: -s/--symbol %%2 > %%1 (list or csv) > SB_SYMBOLS env > GOLD ---
set "SB_UNIVERSE_SRC="
if /i "%~1"=="-s" goto :univ_from_s_flag
if /i "%~1"=="--symbol" goto :univ_from_s_flag
if not "%~1"=="" goto :univ_from_arg1
if defined SB_SYMBOLS goto :univ_from_env
goto :univ_from_gold

:univ_from_s_flag
if "%~2"=="" (
  echo ERROR: %~1 requires a comma-separated symbol list ^(or quoted list^)
  echo Example: SB_ATR_52w_ab.bat -s HROW,REAL,AKR
  echo Example: SB_ATR_52w_ab.bat -s "HROW,REAL,AKR"
  exit /b 1
)
rem Join %%2.. when cmd split an unquoted comma list into separate argv
set "SB_SYMBOLS=%~2"
shift
shift
:univ_join_s
if "%~1"=="" goto :univ_join_s_done
set "SB_JOIN_TOK=%~1"
if "!SB_JOIN_TOK:~0,1!"=="-" goto :univ_join_s_done
set "SB_SYMBOLS=!SB_SYMBOLS!,!SB_JOIN_TOK!"
shift
goto :univ_join_s
:univ_join_s_done
set "SB_UNIVERSE_SRC=-s"
echo [SB AB] Universe: from -s/--symbol
goto :univ_resolved

:univ_from_arg1
if exist "%~1" (
  set /p SB_SYMBOLS=<"%~1"
  set "SB_UNIVERSE_SRC=file:%~1"
  echo [SB AB] Universe: from file "%~1"
  goto :univ_resolved
)
if exist "%~dp0%~1" (
  set /p SB_SYMBOLS=<"%~dp0%~1"
  set "SB_UNIVERSE_SRC=file:%~dp0%~1"
  echo [SB AB] Universe: from file "%~dp0%~1"
  goto :univ_resolved
)
rem Bare comma list may arrive pre-split ^(HROW REAL AKR^) — join ticker-like argv
set "SB_SYMBOLS=%~1"
shift
:univ_join_a
if "%~1"=="" goto :univ_join_a_done
set "SB_JOIN_TOK=%~1"
if "!SB_JOIN_TOK:~0,1!"=="-" goto :univ_join_a_done
set "SB_SYMBOLS=!SB_SYMBOLS!,!SB_JOIN_TOK!"
shift
goto :univ_join_a
:univ_join_a_done
set "SB_UNIVERSE_SRC=%%1"
echo [SB AB] Universe: from %%1 comma list
goto :univ_resolved

:univ_from_env
set "SB_UNIVERSE_SRC=env"
echo [SB AB] Universe: SB_SYMBOLS env
goto :univ_resolved

:univ_from_gold
if not exist "%GOLD%" (
  echo ERROR: missing gold universe: %GOLD%
  exit /b 1
)
set /p SB_SYMBOLS=<%GOLD%
set "SB_UNIVERSE_SRC=GOLD"
echo [SB AB] Universe: GOLD from %GOLD%
goto :univ_resolved

:univ_resolved
rem Strip accidental quote characters left in values
if defined SB_SYMBOLS set SB_SYMBOLS=!SB_SYMBOLS:"=!
if not defined SB_SYMBOLS (
  echo ERROR: SB_SYMBOLS empty after universe resolve
  exit /b 1
)
if /i "!SB_SYMBOLS!"=="-s" goto :univ_bad_resolved
if /i "!SB_SYMBOLS!"=="--symbol" goto :univ_bad_resolved
goto :univ_ok

:univ_bad_resolved
echo ERROR: SB_SYMBOLS is the flag "!SB_SYMBOLS!" — not a ticker list
echo Use: SB_ATR_52w_ab.bat -s HROW,REAL,AKR   or   SB_ATR_52w_ab.bat "HROW,REAL,AKR"
exit /b 1

:univ_ok
rem Bulletproof handoff: write one-line csv, reload into SB_SYMBOLS (survives call/commas)
set "SB_UNIV_FILE=%TEMP%\sb_atr_universe_%RANDOM%%RANDOM%.csv"
> "!SB_UNIV_FILE!" echo !SB_SYMBOLS!
set /p SB_SYMBOLS=<"!SB_UNIV_FILE!"
if not defined SB_SYMBOLS (
  echo ERROR: failed to materialize universe file "!SB_UNIV_FILE!"
  exit /b 1
)
echo [SB AB] Universe file: !SB_UNIV_FILE!
echo [SB AB] Symbols: !SB_SYMBOLS!
echo [SB AB] Workers=%SB_WORKERS%  Out=%DRIVE_OUT%\  (+ arm copies under %OUT%\^<arm^>)
echo [SB AB] Gates: atr_min=!ATR_MIN!  dist52_min=!DIST52_MIN!  ^(control / atr / dist52 / both^)
if /i "%SB_ATR_RESOLVE_ONLY%"=="1" (
  echo [SB AB] SB_ATR_RESOLVE_ONLY=1 — universe OK, exiting before arms
  if exist "!SB_UNIV_FILE!" del /q "!SB_UNIV_FILE!" >nul 2>&1
  exit /b 0
)
if /i "%SB_ATR_SMOKE%"=="1" echo [SB AB] SB_ATR_SMOKE=1 — running 00_control only
if /i "%SB_ATR_SMOKE%"=="true" echo [SB AB] SB_ATR_SMOKE=true — running 00_control only
echo.

set "TOTAL=4"
set "IDX=0"
set "FAIL_COUNT=0"
set "STAMPS_SEEN="

if /i "%SB_ATR_SMOKE%"=="1" goto :smoke_one_arm
if /i "%SB_ATR_SMOKE%"=="true" goto :smoke_one_arm

call :run_arm 00_control ""
call :run_arm 01_atr_only "-v burst_min_atr_pct_at_trigger=!ATR_MIN!"
call :run_arm 02_dist52_only "-v burst_min_dist_to_52w_high_pct=!DIST52_MIN!"
call :run_arm 03_atr_and_dist52 "-v burst_min_atr_pct_at_trigger=!ATR_MIN! -v burst_min_dist_to_52w_high_pct=!DIST52_MIN!"
goto :suite_done

:smoke_one_arm
set "TOTAL=1"
call :run_arm 00_control ""
goto :suite_done

:suite_done
echo.
echo === Suite finished: FAIL_COUNT=!FAIL_COUNT! / %TOTAL% ===
if defined STAMPS_SEEN echo [SB AB] Stamps seen: !STAMPS_SEEN!
if exist "!SB_UNIV_FILE!" del /q "!SB_UNIV_FILE!" >nul 2>&1
if /i "%SB_ATR_SMOKE%"=="1" goto :skip_summary
if /i "%SB_ATR_SMOKE%"=="true" goto :skip_summary
echo Summarizing under %OUT%\ ...
"%PY%" "%~dp0tools\summarize_sb_atr_52w_ab.py" --root "%OUT%"
if errorlevel 1 echo WARN: summary script failed errorlevel=!ERRORLEVEL!
echo.
echo Docs: %OUT%\README.md  and  %OUT%\comparison.html
echo Re-run: SB_ATR_52w_ab.bat   ^(or run_sb_ab_atr_52w.bat^)
goto :exit_rc

:skip_summary
echo [SB AB] Smoke mode — skipped summarize_sb_atr_52w_ab.py
goto :exit_rc

:exit_rc
if !FAIL_COUNT! gtr 0 exit /b 1
exit /b 0

goto :eof

:run_arm
set "ARM=%~1"
set "EXTRA=%~2"
set /a IDX+=1
echo.
echo ========== [!IDX!/%TOTAL%] !ARM! ==========
if not exist "%OUT%\%ARM%" mkdir "%OUT%\%ARM%"
if not exist "%DRIVE_OUT%" mkdir "%DRIVE_OUT%"
rem Re-load symbols from univ file each arm (guards against child clobbering)
if exist "!SB_UNIV_FILE!" set /p SB_SYMBOLS=<"!SB_UNIV_FILE!"
echo CMD: run_stockbee_burst.bat + !EXTRA!
echo [SB AB] -s "!SB_SYMBOLS!"
rem SB_SYMBOLS already resolved; run_stockbee_burst passes -s "!SB_SYMBOLS!" via delayed expansion.
call "%~dp0run_stockbee_burst.bat" !EXTRA!
set "RC=!ERRORLEVEL!"
if !RC! neq 0 (
  echo WARN errorlevel=!RC! on !ARM! - will still try mirror if SB_* wrote
)
set "STAMP="
set "AUD="
for /f "delims=" %%F in ('dir /b /o-d "%DRIVE_OUT%\SB_Audit_Report_*.csv" 2^>nul') do (
  set "AUD=%%F"
  goto :run_arm_got_aud
)
:run_arm_got_aud
if defined AUD (
  for /f "tokens=4 delims=_" %%S in ("!AUD!") do set "STAMP=%%~nS"
)
if not defined STAMP (
  echo FAILED !ARM! - could not detect stamp to mirror into arm folder
  set /a FAIL_COUNT+=1
  goto :eof
)
if not exist "%OUT%\%ARM%" mkdir "%OUT%\%ARM%"
set "DEST=%OUT%\%ARM%"
echo OK !ARM! stamp=!STAMP! - copying SB_*_!STAMP!.* to !DEST!
if defined STAMPS_SEEN (
  set "STAMPS_SEEN=!STAMPS_SEEN! !STAMP!"
) else (
  set "STAMPS_SEEN=!STAMP!"
)
set "COPY_COUNT=0"
for %%F in (%DRIVE_OUT%\SB_*_!STAMP!.*) do (
  if exist "%%~F" (
    copy /Y "%%~F" "!DEST!" >nul
    if not errorlevel 1 set /a COPY_COUNT+=1
  )
)
rem Also copy EquityCurve if present (may use different naming)
for %%F in (%DRIVE_OUT%\SB_EquityCurve*_!STAMP!.*) do (
  if exist "%%~F" (
    copy /Y "%%~F" "!DEST!" >nul
    if not errorlevel 1 set /a COPY_COUNT+=1
  )
)
echo stamp=!STAMP!> "!DEST!\STAMP.txt"
echo arm=!ARM!>> "!DEST!\STAMP.txt"
echo extra=!EXTRA!>> "!DEST!\STAMP.txt"
echo symbols=!SB_SYMBOLS!>> "!DEST!\STAMP.txt"
if !COPY_COUNT! equ 0 (
  echo FAILED mirror: zero files copied for stamp=!STAMP! on !ARM!
  set /a FAIL_COUNT+=1
) else if !RC! neq 0 (
  echo Mirrored !COPY_COUNT! files for !ARM! ^(despite rocket_tbn errorlevel=!RC!^)
  set /a FAIL_COUNT+=1
) else (
  echo Mirrored !COPY_COUNT! files for !ARM!
)
goto :eof
