@echo off
rem RS fat-gap A/B — quick arms for theories still in play (not ruled-out stop/bd/sma20).
rem
rem How to run:
rem   run_rs_ab.bat
rem   (optional) set RS_SYMBOLS=AAPL,MSFT & set RS_WORKERS=11 & run_rs_ab.bat
rem
rem Theories covered:
rem   1) control          — current run_rs.bat levers (stop 0.88, bd=off, atr_days=0)
rem   2) max_atr_pct      — skip high-ATR entries (3.5 / 4.0 / 5.18 from rs_atr_pct grid)
rem   3) atr_days timed   — atr_days + atr_progress=0 (45 / 60 / 90)
rem   4) SPY-INT weak     — entry filter / exit-on-weak / both
rem   5) atr_stop light   — ATR-multiple stop (2 / 3 / 4), fixed target kept
rem
rem Ruled out (NOT in this bat): tighter stop_pct, breakdown_plus, sma_stop_days=20.
rem Does NOT change production run_rs.bat defaults.
rem
rem Compare: after suite, Summary table (Total_PNL / Max_DD / trades) + Closed GAP_DOWN
rem   counts via tools\summarize_rs_fat_gap_ab.py (auto-run at end).
rem Output:
rem   - Primary (concat-friendly): drive\RS_*_<stamp>.csv  (each arm gets a unique stamp)
rem   - Organized copies: drive\paul_experiments\rs_fat_gap_ab\<arm_name>\
rem After suite: concat.bat rs   (or concat.bat rs <stamp-prefix> to narrow)
rem
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

if not defined RS_TARGET set "RS_TARGET=1.25"
if not defined RS_STOP set "RS_STOP=0.88"
if not defined RS_WORKERS set "RS_WORKERS=17"
if not defined RS_SYMBOLS set "RS_SYMBOLS=AAPL,NVDA,GOOGL,MSFT,AMZN,TSM,AVGO,META,LLY,JPM,WMT,MU,AMD,V,XOM,ASML,MA"

set "DRIVE_OUT=drive"
set "OUT=drive\paul_experiments\rs_fat_gap_ab"
set "BASE=-v rs_mode=true -v brt_zones=false -v yh_zones=false -v wpbr_zones=false -v rl_mode=false -v target_pct=%RS_TARGET% -v stop_pct=%RS_STOP% -v stop_pct_is_multiplier=true -v use_indicators=true -v indicator_buy=off -v rs_require_tc_strong=true -v growth_filter_enabled=false -v min_spy_compare_1y_at_trigger=0 -v atr_days=0 -v atr_progress=0 -v too_high_multiplier=0 -v rs_max_pct_below_52w_high=0 -v rs_spy_int_tc_not_weak=false -v max_atr_pct_at_trigger=0 -v atr_stop=0 -v atr_target=0 -v exit_when_spy_int_turns_weak=false"

set "TOTAL=13"
set "IDX=0"
set "FAIL_COUNT=0"

echo === RS fat-gap A/B: %TOTAL% arms ===
echo Seed: %RS_SYMBOLS%
echo Workers: %RS_WORKERS%  Out: %DRIVE_OUT%\  (+ arm copies under %OUT%\^<arm^>)
echo Continues on arm failure (notes errorlevel); summary at end.
echo.

call :run_arm 01_control ""
call :run_arm 02_max_atr_3p5 "-v max_atr_pct_at_trigger=3.5"
call :run_arm 03_max_atr_4p0 "-v max_atr_pct_at_trigger=4.0"
call :run_arm 04_max_atr_5p18 "-v max_atr_pct_at_trigger=5.18"
call :run_arm 05_atr_days_45 "-v atr_days=45 -v atr_progress=0"
call :run_arm 06_atr_days_60 "-v atr_days=60 -v atr_progress=0"
call :run_arm 07_atr_days_90 "-v atr_days=90 -v atr_progress=0"
call :run_arm 08_spy_int_entry "-v rs_spy_int_tc_not_weak=true"
call :run_arm 09_spy_int_exit "-v exit_when_spy_int_turns_weak=true"
call :run_arm 10_spy_int_both "-v rs_spy_int_tc_not_weak=true -v exit_when_spy_int_turns_weak=true"
call :run_arm 11_atr_stop_2 "-v atr_stop=2 -v atr_target=0"
call :run_arm 12_atr_stop_3 "-v atr_stop=3 -v atr_target=0"
call :run_arm 13_atr_stop_4 "-v atr_stop=4 -v atr_target=0"

echo.
echo === Suite finished: FAIL_COUNT=!FAIL_COUNT! / %TOTAL% ===
echo Summarizing RS_Report + GAP_DOWN under %OUT%\ ...
"%PY%" "%~dp0tools\summarize_rs_fat_gap_ab.py" --root "%OUT%"
if errorlevel 1 echo WARN: summary script failed errorlevel=!ERRORLEVEL!
echo.
echo Concat for optimizer sheet (from repo root):
echo   concat.bat rs
echo   ^(or narrow by stamp prefix, e.g. concat.bat rs 260731204^)
echo Writes drive\all_rs.csv from drive\RS_Audit_Report_*.csv

if !FAIL_COUNT! gtr 0 exit /b 1
exit /b 0

:run_arm
set "ARM=%~1"
set "EXTRA=%~2"
set /a IDX+=1
echo.
echo ========== [!IDX!/%TOTAL%] !ARM! ==========
if not exist "%OUT%\!ARM!" mkdir "%OUT%\!ARM!"
if not exist "%DRIVE_OUT%" mkdir "%DRIVE_OUT%"
echo CMD: rocket_tbn --relative-strength BASE + !EXTRA!  (-o %DRIVE_OUT%)
"%PY%" stock_analysis\rocket_tbn.py data\newdata\data -o "%DRIVE_OUT%" -w %RS_WORKERS% --no-regression --aggressive --relative-strength %BASE% %EXTRA% -s "%RS_SYMBOLS%"
set "RC=!ERRORLEVEL!"
if !RC! neq 0 (
  echo WARN errorlevel=!RC! on !ARM! - will still try mirror if RS_* wrote
)
rem Mirror this arm's newest stamp into the arm subfolder for summarize_rs_fat_gap_ab.py
rem Stamp from newest RS_Audit_Report_*.csv (not log ts= parse)
set "STAMP="
set "AUD="
for /f "delims=" %%F in ('dir /b /o-d "%DRIVE_OUT%\RS_Audit_Report_*.csv" 2^>nul') do (
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
rem Unquoted for-set so wildcards expand; never use "%OUT%\!ARM%\" (\! / trailing \" breaks under delayed expansion)
if not exist "%OUT%\!ARM!" mkdir "%OUT%\!ARM!"
echo OK !ARM! stamp=!STAMP! - copying RS_*_!STAMP!.* to %OUT%\!ARM!\
set "COPY_COUNT=0"
for %%F in (%DRIVE_OUT%\RS_*_!STAMP!.*) do (
  if exist "%%~F" (
    copy /Y "%%~F" "%OUT%\!ARM%" >nul
    if not errorlevel 1 set /a COPY_COUNT+=1
  )
)
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
