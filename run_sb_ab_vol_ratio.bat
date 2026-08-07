@echo off
rem StockBee Momentum Burst A/B: Vol >= k x prior-50d average (burst_vol_vs_avg_mult).
rem Does NOT change production run_sb.bat / run_stockbee_burst.bat defaults.
rem Root alias: SB_Vol_ab.bat (preferred one-liner for custom universe).
rem
rem Spec: drive\paul_experiments\tbn_new_systems\stockbee_momentum_burst\SB_NEXT_BUILDS.md
rem   Priority 4 — Vol >= 1.5-2x 50d avg
rem   VOL_VS_50 = V[T] / mean(V[T-lookback .. T-1]); exclude signal bar
rem   Gate ON when burst_vol_vs_avg_mult > 0; fail closed if MA undefined
rem   Note: Closed DNA VOL_RATIO is V[T]/V[T-1] (different); gate uses VOL_VS_50
rem
rem EDIT SETTINGS: change VOL_RATIO_* / RUN_* in the "EDIT DEFAULTS HERE" block
rem   below — save, then run. Env override still works if already set.
rem
rem Arms (thresholds from settings block):
rem   00_control     — gate OFF (burst_vol_vs_avg_mult=0)
rem   01_vol_1_25    — mult=VOL_RATIO_1_25 (default 1.25)
rem   02_vol_1_5     — mult=VOL_RATIO_1_5  (default 1.5)
rem   03_vol_1_75    — mult=VOL_RATIO_1_75 (default 1.75)
rem   04_vol_2_0     — mult=VOL_RATIO_2_0  (default 2.0)
rem   05_vol_2_5     — mult=VOL_RATIO_2_5  (default 2.5)
rem
rem Universe (first match wins):
rem   -s / --symbol LIST   e.g. SB_Vol_ab.bat -s HROW,REAL,AKR
rem   %%1 comma list       e.g. SB_Vol_ab.bat HROW,REAL,AKR
rem   %%1 path to GOLD-style csv (one line of tickers)
rem   SB_SYMBOLS env       (or uncomment set in settings block)
rem   else GOLD_UNIVERSE.csv
rem
rem How to run:
rem   SB_Vol_ab.bat
rem   SB_Vol_ab.bat HROW,REAL,AKR
rem   SB_Vol_ab.bat -s HROW,REAL,AKR
rem   run_sb_ab_vol_ratio.bat
rem   (optional) set SB_VOL_SMOKE=1  — run 00_control only
rem   (optional) set SB_VOL_RESOLVE_ONLY=1 — universe + Gates echo, no arms
rem
rem Output:
rem   - Primary: drive\SB_*_<stamp>.csv
rem   - Copies:  drive\paul_experiments\tbn_new_systems\stockbee_momentum_burst\ab_vol_ratio\<arm>\
rem After suite: tools\summarize_sb_vol_ratio_ab.py writes HTML+MD comparison.
rem
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

rem === EDIT DEFAULTS HERE (open this file, change values, save, run) ===
rem Env already set before call still wins (if not defined).
if not defined VOL_RATIO_1_25 set "VOL_RATIO_1_25=1.25"
if not defined VOL_RATIO_1_5 set "VOL_RATIO_1_5=1.5"
if not defined VOL_RATIO_1_75 set "VOL_RATIO_1_75=1.75"
if not defined VOL_RATIO_2_0 set "VOL_RATIO_2_0=2.0"
if not defined VOL_RATIO_2_5 set "VOL_RATIO_2_5=2.5"
if not defined VOL_AVG_LOOKBACK set "VOL_AVG_LOOKBACK=50"
if not defined SB_WORKERS set "SB_WORKERS=0"
if not defined SB_AGGRESSIVE set "SB_AGGRESSIVE=true"
rem Toggle arms (1/true = run). Control always runs unless smoke/resolve-only.
if not defined RUN_VOL_1_25 set "RUN_VOL_1_25=1"
if not defined RUN_VOL_1_5 set "RUN_VOL_1_5=1"
if not defined RUN_VOL_1_75 set "RUN_VOL_1_75=1"
if not defined RUN_VOL_2_0 set "RUN_VOL_2_0=1"
if not defined RUN_VOL_2_5 set "RUN_VOL_2_5=1"
rem if not defined SB_SYMBOLS set "SB_SYMBOLS=HROW,REAL,AKR"
rem === end defaults ===

set "DRIVE_OUT=drive"
set "OUT=drive\paul_experiments\tbn_new_systems\stockbee_momentum_burst\ab_vol_ratio"
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
  echo Example: SB_Vol_ab.bat -s HROW,REAL,AKR
  echo Example: SB_Vol_ab.bat -s "HROW,REAL,AKR"
  exit /b 1
)
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
echo Use: SB_Vol_ab.bat -s HROW,REAL,AKR   or   SB_Vol_ab.bat "HROW,REAL,AKR"
exit /b 1

:univ_ok
set "SB_UNIV_FILE=%TEMP%\sb_vol_universe_%RANDOM%%RANDOM%.csv"
> "!SB_UNIV_FILE!" echo !SB_SYMBOLS!
set /p SB_SYMBOLS=<"!SB_UNIV_FILE!"
if not defined SB_SYMBOLS (
  echo ERROR: failed to materialize universe file "!SB_UNIV_FILE!"
  exit /b 1
)
echo [SB AB] Universe file: !SB_UNIV_FILE!
echo [SB AB] Symbols: !SB_SYMBOLS!
echo [SB AB] Workers=%SB_WORKERS%  Out=%DRIVE_OUT%\  (+ arm copies under %OUT%\^<arm^>)
echo [SB AB] Gates: lookback=!VOL_AVG_LOOKBACK!  1.25=!VOL_RATIO_1_25!  1.5=!VOL_RATIO_1_5!  1.75=!VOL_RATIO_1_75!  2.0=!VOL_RATIO_2_0!  2.5=!VOL_RATIO_2_5!
if /i "%SB_VOL_RESOLVE_ONLY%"=="1" (
  echo [SB AB] SB_VOL_RESOLVE_ONLY=1 — universe OK, exiting before arms
  if exist "!SB_UNIV_FILE!" del /q "!SB_UNIV_FILE!" >nul 2>&1
  exit /b 0
)
if /i "%SB_VOL_SMOKE%"=="1" echo [SB AB] SB_VOL_SMOKE=1 — running 00_control only
if /i "%SB_VOL_SMOKE%"=="true" echo [SB AB] SB_VOL_SMOKE=true — running 00_control only
echo.

set "TOTAL=0"
set "IDX=0"
set "FAIL_COUNT=0"
set "STAMPS_SEEN="

if /i "%SB_VOL_SMOKE%"=="1" goto :smoke_one_arm
if /i "%SB_VOL_SMOKE%"=="true" goto :smoke_one_arm

rem Pre-count arms for progress display
set /a TOTAL+=1
if /i "%RUN_VOL_1_25%"=="1" set /a TOTAL+=1
if /i "%RUN_VOL_1_25%"=="true" set /a TOTAL+=1
if /i "%RUN_VOL_1_5%"=="1" set /a TOTAL+=1
if /i "%RUN_VOL_1_5%"=="true" set /a TOTAL+=1
if /i "%RUN_VOL_1_75%"=="1" set /a TOTAL+=1
if /i "%RUN_VOL_1_75%"=="true" set /a TOTAL+=1
if /i "%RUN_VOL_2_0%"=="1" set /a TOTAL+=1
if /i "%RUN_VOL_2_0%"=="true" set /a TOTAL+=1
if /i "%RUN_VOL_2_5%"=="1" set /a TOTAL+=1
if /i "%RUN_VOL_2_5%"=="true" set /a TOTAL+=1

call :run_arm 00_control ""
if /i "%RUN_VOL_1_25%"=="1" call :run_arm 01_vol_1_25 "-v burst_vol_vs_avg_mult=!VOL_RATIO_1_25! -v burst_vol_avg_lookback=!VOL_AVG_LOOKBACK!"
if /i "%RUN_VOL_1_25%"=="true" call :run_arm 01_vol_1_25 "-v burst_vol_vs_avg_mult=!VOL_RATIO_1_25! -v burst_vol_avg_lookback=!VOL_AVG_LOOKBACK!"
if /i "%RUN_VOL_1_5%"=="1" call :run_arm 02_vol_1_5 "-v burst_vol_vs_avg_mult=!VOL_RATIO_1_5! -v burst_vol_avg_lookback=!VOL_AVG_LOOKBACK!"
if /i "%RUN_VOL_1_5%"=="true" call :run_arm 02_vol_1_5 "-v burst_vol_vs_avg_mult=!VOL_RATIO_1_5! -v burst_vol_avg_lookback=!VOL_AVG_LOOKBACK!"
if /i "%RUN_VOL_1_75%"=="1" call :run_arm 03_vol_1_75 "-v burst_vol_vs_avg_mult=!VOL_RATIO_1_75! -v burst_vol_avg_lookback=!VOL_AVG_LOOKBACK!"
if /i "%RUN_VOL_1_75%"=="true" call :run_arm 03_vol_1_75 "-v burst_vol_vs_avg_mult=!VOL_RATIO_1_75! -v burst_vol_avg_lookback=!VOL_AVG_LOOKBACK!"
if /i "%RUN_VOL_2_0%"=="1" call :run_arm 04_vol_2_0 "-v burst_vol_vs_avg_mult=!VOL_RATIO_2_0! -v burst_vol_avg_lookback=!VOL_AVG_LOOKBACK!"
if /i "%RUN_VOL_2_0%"=="true" call :run_arm 04_vol_2_0 "-v burst_vol_vs_avg_mult=!VOL_RATIO_2_0! -v burst_vol_avg_lookback=!VOL_AVG_LOOKBACK!"
if /i "%RUN_VOL_2_5%"=="1" call :run_arm 05_vol_2_5 "-v burst_vol_vs_avg_mult=!VOL_RATIO_2_5! -v burst_vol_avg_lookback=!VOL_AVG_LOOKBACK!"
if /i "%RUN_VOL_2_5%"=="true" call :run_arm 05_vol_2_5 "-v burst_vol_vs_avg_mult=!VOL_RATIO_2_5! -v burst_vol_avg_lookback=!VOL_AVG_LOOKBACK!"
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
if /i "%SB_VOL_SMOKE%"=="1" goto :skip_summary
if /i "%SB_VOL_SMOKE%"=="true" goto :skip_summary
if !FAIL_COUNT! gtr 0 (
  echo FAIL: one or more arms failed — skipping summarize ^(no stale comparison^)
  goto :exit_rc
)
echo Summarizing under %OUT%\ ...
"%PY%" "%~dp0tools\summarize_sb_vol_ratio_ab.py" --root "%OUT%"
if errorlevel 1 echo WARN: summary script failed errorlevel=!ERRORLEVEL!
echo.
echo Docs: %OUT%\README.md  and  %OUT%\comparison.html
echo Re-run: SB_Vol_ab.bat   ^(or run_sb_ab_vol_ratio.bat^)
goto :exit_rc

:skip_summary
echo [SB AB] Smoke mode — skipped summarize_sb_vol_ratio_ab.py
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
if exist "!SB_UNIV_FILE!" set /p SB_SYMBOLS=<"!SB_UNIV_FILE!"
echo CMD: run_stockbee_burst.bat + !EXTRA!
echo [SB AB] -s "!SB_SYMBOLS!"
call "%~dp0run_stockbee_burst.bat" !EXTRA!
set "RC=!ERRORLEVEL!"
if !RC! neq 0 (
  echo FAILED !ARM! rocket errorlevel=!RC! — NOT mirroring ^(avoid stale stamps^)
  set /a FAIL_COUNT+=1
  goto :eof
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
) else (
  echo Mirrored !COPY_COUNT! files for !ARM!
)
goto :eof
