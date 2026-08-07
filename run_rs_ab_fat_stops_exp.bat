@echo off
rem RS fat_stops A/B — tighter stop_pct + time-stop (atr_days) on expanded FIT universe.
rem
rem How to run (repo root):
rem   run_rs_ab_fat_stops_exp.bat
rem   (optional) set RS_SYMBOLS=AAMI,APLD & set RS_WORKERS=12 & run_rs_ab_fat_stops_exp.bat
rem
rem Context: ImproveHints #1 on expanded RS is fat_stops (STOP losses dominate).
rem Prior seed AB (rs_fat_gap_ab) ruled out tighter stop_pct — hurt PnL on the
rem 17-name seed. Re-test on the expanded FIT>=6 universe with current production
rem BASE (spy_int + cd=60). RS has no cut_the_losers; use atr_days time-stop instead.
rem Does NOT change production run_rs.bat defaults.
rem
rem Suite BASE = production run_rs.bat / reconcile freeze: stop 0.88 / target 1.25 + spy_int + cd=60.
rem Research-only stamp 260801104344 used 0.934/1.21 — not production.
rem User rejected arm 03_stop_091; do not promote 0.91 into production.
rem Seed = expanded FIT-robust list from run_rs.bat (override via RS_SYMBOLS)
rem
rem Arms (~10) — EXTRA on top of suite BASE (0.88/1.25 = current production):
rem   01_control          — stop 0.88 (production / reconcile freeze control)
rem   02-06 stop_0XX      — tighter stop_pct 0.90 / 0.91 / 0.92 / 0.93 / 0.94
rem                         (higher multiplier = tighter for RS stop_pct_is_multiplier)
rem   07-08 atr_days_*    — time-stop atr_days=45/60 + atr_progress=0
rem   09-10 atr_stop_*    — ATR-multiple stop 2/3 with stop_pct=0 (fixed target kept)
rem
rem Output:
rem   - Primary: drive\RS_*_<stamp>.csv
rem   - Copies:  drive\paul_experiments\rs_fat_stops_exp_ab\<arm>\
rem After suite: tools\summarize_rs_fat_stops_exp_ab.py (auto-run)
rem Concat: concat.bat rs
rem
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

if not defined RS_TARGET set "RS_TARGET=1.25"
if not defined RS_STOP set "RS_STOP=0.88"
if not defined RS_WORKERS set "RS_WORKERS=12"
rem Same expanded list as run_rs.bat (FIT>=6); override with set RS_SYMBOLS=...
if not defined RS_SYMBOLS set "RS_SYMBOLS=APLD,BELFA,DECK,LMND,PLTR,PRI,SAFRY,WELL,AAMI,ABBNY,ACGL,BDGIF,BFC,BIO,CTAS,DDOG,FIS,FISV,HWM,JACK,JNJ,JOE,NEE,NTAP,ORLY,SNPS,SSUMY,TMUS,TRV,WMT,ALBY,AME,AWK,BSX,D,DHR,EADSY,FOXA,HSBC,HSY,IBM,ISRG,IT,ITW,LII,LUV,MLI,MOS,MSCI,ODFL,RNG,SLG,TJX,USB"

set "DRIVE_OUT=drive"
set "OUT=drive\paul_experiments\rs_fat_stops_exp_ab"
rem Suite BASE levers (spy_int + cd=60 + stop 0.88/target 1.25); arms override stop / atr.
set "BASE=-v rs_mode=true -v brt_zones=false -v yh_zones=false -v wpbr_zones=false -v rl_mode=false -v target_pct=%RS_TARGET% -v stop_pct=%RS_STOP% -v stop_pct_is_multiplier=true -v use_indicators=true -v indicator_buy=off -v rs_require_tc_strong=true -v growth_filter_enabled=false -v min_spy_compare_1y_at_trigger=0 -v atr_days=0 -v atr_progress=0 -v too_high_multiplier=0 -v rs_max_pct_below_52w_high=0 -v rs_spy_int_tc_not_weak=true -v max_atr_pct_at_trigger=0 -v atr_stop=0 -v atr_target=0 -v exit_when_spy_int_turns_weak=false -v sell_breakdown=off -v symbol_reentry_cooldown_days=60"

set "TOTAL=10"
set "IDX=0"
set "FAIL_COUNT=0"

echo === RS fat_stops A/B (production BASE spy_int+cd60): %TOTAL% arms ===
echo Seed: %RS_SYMBOLS%
echo Workers: %RS_WORKERS%  Out: %DRIVE_OUT%\  (+ arm copies under %OUT%\^<arm^>)
echo Continues on arm failure (notes errorlevel); summary at end.
echo.

call :run_arm 01_control ""
call :run_arm 02_stop_090 "-v stop_pct=0.90"
call :run_arm 03_stop_091 "-v stop_pct=0.91"
call :run_arm 04_stop_092 "-v stop_pct=0.92"
call :run_arm 05_stop_093 "-v stop_pct=0.93"
call :run_arm 06_stop_094 "-v stop_pct=0.94"
call :run_arm 07_atr_days_45 "-v atr_days=45 -v atr_progress=0"
call :run_arm 08_atr_days_60 "-v atr_days=60 -v atr_progress=0"
call :run_arm 09_atr_stop_2 "-v atr_stop=2 -v atr_target=0 -v stop_pct=0"
call :run_arm 10_atr_stop_3 "-v atr_stop=3 -v atr_target=0 -v stop_pct=0"

echo.
echo === Suite finished: FAIL_COUNT=!FAIL_COUNT! / %TOTAL% ===
echo Summarizing RS_Report + fat_stops under %OUT%\ ...
"%PY%" "%~dp0tools\summarize_rs_fat_stops_exp_ab.py" --root "%OUT%"
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
rem Mirror this arm's newest stamp into the arm subfolder.
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
