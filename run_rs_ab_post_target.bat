@echo off
rem RS post-TARGET quick-stop A/B — ImproveHints post_target_quick_stop
rem (TARGET then immediate re-entry → STOP in ≤10d). Separate from fat-gap
rem (run_rs_ab.bat) and false-start (run_rs_ab_false_start.bat). Does NOT
rem change production run_rs.bat defaults.
rem
rem How to run:
rem   run_rs_ab_post_target.bat
rem   (optional) set RS_SYMBOLS=AAPL,MSFT & set RS_WORKERS=11 & run_rs_ab_post_target.bat
rem
rem Seed: production 17-name run_rs.bat list (full seed for fair PnL). Hint symbols:
rem   ImproveHints: ASML,NVDA,TSLA,TSM
rem   In seed: ASML,NVDA,TSM | Out: TSLA (dropped from current run_rs list)
rem
rem Inventory (RS path only — rocket_tbn / BRTConfig):
rem   PRIMARY: symbol_reentry_cooldown_days — calendar days after ANY exit before
rem     same-symbol re-entry (0=off). Wired in RS backtest (~rocket_tbn RS loop).
rem     NOT post-TARGET-only: also delays re-entry after STOP/breakdown.
rem   RL-ONLY (do NOT use here): rl_post_target_reentry_bars / _mode / _stop_pct /
rem     _min_stack / _under_sma20 — honored only when rl_mode=true (rocket_rl).
rem     Prefer those for RL; for RS stick to symbol_reentry_cooldown_days.
rem   SECONDARY re-entry filters (gate all entries, incl. post-TARGET):
rem     rs_spy_int_tc_not_weak, rs_max_pct_below_52w_high, growth_filter_enabled.
rem
rem Theories covered (real RS flags only):
rem   1) control              — current run_rs.bat levers (cooldown=0)
rem   2-7) cooldown grid      — symbol_reentry_cooldown_days = 3/5/10/15/20/30
rem   8) spy_int entry        — rs_spy_int_tc_not_weak (stricter re-entry)
rem   9) near 52w high        — rs_max_pct_below_52w_high=0.15
rem  10) combo                — cd=10 + spy_int entry
rem  11) growth_252           — Close_T >= Close_{T-252} (light secondary)
rem
rem Tradeoff (document): no RS post-win-only cooldown exists; blanket cooldown
rem   is the real lever. It may also block healthy re-entries after STOP.
rem
rem Output:
rem   - Primary (concat-friendly): drive\RS_*_<stamp>.csv  (each arm unique stamp)
rem   - Organized copies: drive\paul_experiments\rs_post_target_ab\<arm_name>\
rem After suite: Summary (PnL / Max_DD / post_target_quick_stop ≤10d) via
rem   tools\summarize_rs_post_target_ab.py (auto-run at end).
rem Concat: concat.bat rs   (or concat.bat rs <stamp-prefix>)
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
set "OUT=drive\paul_experiments\rs_post_target_ab"
set "BASE=-v rs_mode=true -v brt_zones=false -v yh_zones=false -v wpbr_zones=false -v rl_mode=false -v target_pct=%RS_TARGET% -v stop_pct=%RS_STOP% -v stop_pct_is_multiplier=true -v use_indicators=true -v indicator_buy=off -v rs_require_tc_strong=true -v growth_filter_enabled=false -v min_spy_compare_1y_at_trigger=0 -v atr_days=0 -v atr_progress=0 -v too_high_multiplier=0 -v rs_max_pct_below_52w_high=0 -v rs_spy_int_tc_not_weak=false -v max_atr_pct_at_trigger=0 -v atr_stop=0 -v atr_target=0 -v exit_when_spy_int_turns_weak=false -v sell_breakdown=off -v symbol_reentry_cooldown_days=0"

set "TOTAL=11"
set "IDX=0"
set "FAIL_COUNT=0"

echo === RS post-TARGET quick-stop A/B: %TOTAL% arms ===
echo Seed: %RS_SYMBOLS%
echo Hint in-seed: ASML,NVDA,TSM  ^| out: TSLA
echo Workers: %RS_WORKERS%  Out: %DRIVE_OUT%\  (+ arm copies under %OUT%\^<arm^>)
echo Continues on arm failure (notes errorlevel); summary at end.
echo.

call :run_arm 01_control ""
call :run_arm 02_cd_3 "-v symbol_reentry_cooldown_days=3"
call :run_arm 03_cd_5 "-v symbol_reentry_cooldown_days=5"
call :run_arm 04_cd_10 "-v symbol_reentry_cooldown_days=10"
call :run_arm 05_cd_15 "-v symbol_reentry_cooldown_days=15"
call :run_arm 06_cd_20 "-v symbol_reentry_cooldown_days=20"
call :run_arm 07_cd_30 "-v symbol_reentry_cooldown_days=30"
call :run_arm 08_spy_int_entry "-v rs_spy_int_tc_not_weak=true"
call :run_arm 09_near_52w_15 "-v rs_max_pct_below_52w_high=0.15"
call :run_arm 10_cd10_spy_int "-v symbol_reentry_cooldown_days=10 -v rs_spy_int_tc_not_weak=true"
call :run_arm 11_growth_252 "-v growth_filter_enabled=true -v growth_bars=252"

echo.
echo === Suite finished: FAIL_COUNT=!FAIL_COUNT! / %TOTAL% ===
echo Summarizing RS_Report + post_target_quick_stop under %OUT%\ ...
"%PY%" "%~dp0tools\summarize_rs_post_target_ab.py" --root "%OUT%"
if errorlevel 1 echo WARN: summary script failed errorlevel=!ERRORLEVEL!
echo.
echo Concat for optimizer sheet (from repo root):
echo   concat.bat rs
echo   ^(or narrow by stamp prefix, e.g. concat.bat rs 260731^)
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
rem Mirror this arm's newest stamp into the arm subfolder for summarize_rs_post_target_ab.py
rem Stamp from newest RS_Audit_Report_*.csv (same as false_start/fat-gap; not log ts= parse)
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
