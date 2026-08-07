@echo off
rem RS spy_int + cooldown complement A/B — does spy_int entry + calendar
rem re-entry cooldown stack (fewer weak-regime entries AND less short-hold churn)?
rem Separate from fat-gap (run_rs_ab.bat), false-start (run_rs_ab_false_start.bat),
rem and post-TARGET (run_rs_ab_post_target.bat). Does NOT change production run_rs.bat.
rem
rem How to run:
rem   run_rs_ab_spy_cd.bat
rem   (optional) set RS_SYMBOLS=AAPL,MSFT & set RS_WORKERS=11 & run_rs_ab_spy_cd.bat
rem
rem Seed: production 17-name run_rs.bat list (same as other RS ABs).
rem
rem Theories:
rem   1) control              — current run_rs.bat levers (spy_int=false, cd=0)
rem   2) spy_int only         — rs_spy_int_tc_not_weak=true, cd=0
rem   3-8) spy_int + cd grid  — spy_int=true + symbol_reentry_cooldown_days = 3/5/10/15/20/30
rem   9) cd_10 alone          — cooldown=10 without spy_int (contrast / interaction check)
rem
rem Output:
rem   - Primary (concat-friendly): drive\RS_*_<stamp>.csv  (each arm unique stamp)
rem   - Organized copies: drive\paul_experiments\rs_spy_cd_ab\<arm_name>\
rem After suite: Summary (PnL / Max_DD / WR / PTQS / STOP22 + delta vs control) via
rem   tools\summarize_rs_spy_cd_ab.py (auto-run at end).
rem Concat: concat.bat rs   (or concat.bat rs <stamp-prefix>)
rem See also: drive\paul_experiments\rs_spy_cd_ab\README.md
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
set "OUT=drive\paul_experiments\rs_spy_cd_ab"
set "BASE=-v rs_mode=true -v brt_zones=false -v yh_zones=false -v wpbr_zones=false -v rl_mode=false -v target_pct=%RS_TARGET% -v stop_pct=%RS_STOP% -v stop_pct_is_multiplier=true -v use_indicators=true -v indicator_buy=off -v rs_require_tc_strong=true -v growth_filter_enabled=false -v min_spy_compare_1y_at_trigger=0 -v atr_days=0 -v atr_progress=0 -v too_high_multiplier=0 -v rs_max_pct_below_52w_high=0 -v rs_spy_int_tc_not_weak=false -v max_atr_pct_at_trigger=0 -v atr_stop=0 -v atr_target=0 -v exit_when_spy_int_turns_weak=false -v sell_breakdown=off -v symbol_reentry_cooldown_days=0"

set "TOTAL=9"
set "IDX=0"
set "FAIL_COUNT=0"

echo === RS spy_int + cooldown A/B: %TOTAL% arms ===
echo Seed: %RS_SYMBOLS%
echo Workers: %RS_WORKERS%  Out: %DRIVE_OUT%\  (+ arm copies under %OUT%\^<arm^>)
echo Continues on arm failure (notes errorlevel); summary at end.
echo.

call :run_arm 01_control ""
call :run_arm 02_spy_int_only "-v rs_spy_int_tc_not_weak=true"
call :run_arm 03_spy_cd_3 "-v rs_spy_int_tc_not_weak=true -v symbol_reentry_cooldown_days=3"
call :run_arm 04_spy_cd_5 "-v rs_spy_int_tc_not_weak=true -v symbol_reentry_cooldown_days=5"
call :run_arm 05_spy_cd_10 "-v rs_spy_int_tc_not_weak=true -v symbol_reentry_cooldown_days=10"
call :run_arm 06_spy_cd_15 "-v rs_spy_int_tc_not_weak=true -v symbol_reentry_cooldown_days=15"
call :run_arm 07_spy_cd_20 "-v rs_spy_int_tc_not_weak=true -v symbol_reentry_cooldown_days=20"
call :run_arm 08_spy_cd_30 "-v rs_spy_int_tc_not_weak=true -v symbol_reentry_cooldown_days=30"
call :run_arm 09_cd_10_alone "-v symbol_reentry_cooldown_days=10"

echo.
echo === Suite finished: FAIL_COUNT=!FAIL_COUNT! / %TOTAL% ===
echo Summarizing RS_Report + PTQS + STOP22 under %OUT%\ ...
"%PY%" "%~dp0tools\summarize_rs_spy_cd_ab.py" --root "%OUT%"
if errorlevel 1 echo WARN: summary script failed errorlevel=!ERRORLEVEL!
echo.
echo Concat for optimizer sheet (from repo root):
echo   concat.bat rs
echo   ^(or narrow by stamp prefix, e.g. concat.bat rs 260801^)
echo Writes drive\all_rs.csv from drive\RS_Audit_Report_*.csv

if !FAIL_COUNT! gtr 0 exit /b 1
exit /b 0

:run_arm
set "ARM=%~1"
set "EXTRA=%~2"
set /a IDX+=1
echo.
echo ========== [!IDX!/%TOTAL%] !ARM! ==========
if not exist "%OUT%\%ARM%" mkdir "%OUT%\%ARM%"
if not exist "%DRIVE_OUT%" mkdir "%DRIVE_OUT%"
echo CMD: rocket_tbn --relative-strength BASE + !EXTRA!  (-o %DRIVE_OUT%)
"%PY%" stock_analysis\rocket_tbn.py data\newdata\data -o "%DRIVE_OUT%" -w %RS_WORKERS% --no-regression --aggressive --relative-strength %BASE% %EXTRA% -s "%RS_SYMBOLS%"
set "RC=!ERRORLEVEL!"
if !RC! neq 0 (
  echo WARN errorlevel=!RC! on !ARM! - will still try mirror if RS_* wrote
)
rem Mirror this arm's newest stamp into the arm subfolder for summarize_rs_spy_cd_ab.py
rem Stamp from newest RS_Audit_Report_*.csv (same as other RS ABs; not log ts= parse)
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
rem Unquoted for-set so wildcards expand. Never copy to "%OUT%\!ARM%" — under
rem delayed expansion \! eats the bangs and dest becomes ...\ARM (a file).
rem Pre-expand arm dir with %ARM% into DEST, then copy to "!DEST!".
if not exist "%OUT%\%ARM%" mkdir "%OUT%\%ARM%"
set "DEST=%OUT%\%ARM%"
echo OK !ARM! stamp=!STAMP! - copying RS_*_!STAMP!.* to !DEST!
set "COPY_COUNT=0"
for %%F in (%DRIVE_OUT%\RS_*_!STAMP!.*) do (
  if exist "%%~F" (
    copy /Y "%%~F" "!DEST!" >nul
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
