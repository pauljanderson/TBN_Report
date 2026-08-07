@echo off
rem RS post-TARGET v2 A/B — on top of 093239 baseline (spy_int + cd=30).
rem ImproveHints post_target_quick_stop still fires with blanket cd=30
rem (MA TARGET→STOP ~9d; NVDA several 0–10d) → need TARGET-only gates.
rem
rem How to run (repo root):
rem   run_rs_ab_post_target_v2.bat
rem   (optional) set RS_SYMBOLS=AAPL,NVDA & set RS_WORKERS=12 & run_rs_ab_post_target_v2.bat
rem
rem Suite BASE = historical 093239 (spy_int + cd=30). Production run_rs.bat
rem later adopted arm 12_cd_60 (stamp 260801101655); keep BASE at cd=30 for A/B.
rem   rs_spy_int_tc_not_weak=true
rem   symbol_reentry_cooldown_days=30
rem   target 1.25 / stop 0.88
rem   Seed = 12 that trade: AAPL,NVDA,GOOGL,MSFT,AMZN,TSM,AVGO,META,WMT,V,ASML,MA
rem   (drop LLY,JPM,MU,AMD,XOM)
rem
rem Inventory:
rem   RS had only blanket symbol_reentry_cooldown_days (any exit).
rem   RL had rl_post_target_reentry_bars/mode/stop_pct/min_stack/under_sma20
rem     (post-TARGET-only). Those BRTConfig fields are now wired into RS/IND
rem     scan entry via stock_analysis/post_target_reentry.py (shared with RL).
rem
rem Arms (~12) — EXTRA on top of BASE (spy_int + cd30):
rem   01_control          — exact 093239 (post_target off)
rem   02-05 pt_none_*     — bars=10/15/20/30 mode=none (pure post-win cooldown)
rem   06-07 under_sma     — bars=10 under_sma_limit 0.03 / 0.01
rem   08 min_stack        — bars=10 min_stack=0.05
rem   09-10 stop_loss     — bars=10 tighter stop 0.92 / 0.95
rem   11-12 cd fallback   — blanket cd=45 / 60 (post_target still off)
rem
rem Output:
rem   - Primary: drive\RS_*_<stamp>.csv
rem   - Copies:  drive\paul_experiments\rs_post_target_v2_ab\<arm>\
rem After suite: tools\summarize_rs_post_target_ab.py (HINT=MA,NVDA)
rem Concat: concat.bat rs
rem
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

if not defined RS_TARGET set "RS_TARGET=1.25"
if not defined RS_STOP set "RS_STOP=0.88"
if not defined RS_WORKERS set "RS_WORKERS=12"
if not defined RS_SYMBOLS set "RS_SYMBOLS=AAPL,NVDA,GOOGL,MSFT,AMZN,TSM,AVGO,META,WMT,V,ASML,MA"

set "DRIVE_OUT=drive"
set "OUT=drive\paul_experiments\rs_post_target_v2_ab"
rem BASE = 093239 levers (spy_int + cd30); arms add post_target / longer blanket cd.
set "BASE=-v rs_mode=true -v brt_zones=false -v yh_zones=false -v wpbr_zones=false -v rl_mode=false -v target_pct=%RS_TARGET% -v stop_pct=%RS_STOP% -v stop_pct_is_multiplier=true -v use_indicators=true -v indicator_buy=off -v rs_require_tc_strong=true -v growth_filter_enabled=false -v min_spy_compare_1y_at_trigger=0 -v atr_days=0 -v atr_progress=0 -v too_high_multiplier=0 -v rs_max_pct_below_52w_high=0 -v rs_spy_int_tc_not_weak=true -v max_atr_pct_at_trigger=0 -v atr_stop=0 -v atr_target=0 -v exit_when_spy_int_turns_weak=false -v sell_breakdown=off -v symbol_reentry_cooldown_days=30 -v rl_post_target_reentry_bars=0"

set "TOTAL=12"
set "IDX=0"
set "FAIL_COUNT=0"

echo === RS post-TARGET v2 A/B (093239 BASE): %TOTAL% arms ===
echo Seed: %RS_SYMBOLS%
echo Hint symbols: MA,NVDA
echo Workers: %RS_WORKERS%  Out: %DRIVE_OUT%\  (+ arm copies under %OUT%\^<arm^>)
echo Continues on arm failure (notes errorlevel); summary at end.
echo.

call :run_arm 01_control ""
call :run_arm 02_pt_none_10 "-v rl_post_target_reentry_bars=10 -v rl_post_target_reentry_mode=none"
call :run_arm 03_pt_none_15 "-v rl_post_target_reentry_bars=15 -v rl_post_target_reentry_mode=none"
call :run_arm 04_pt_none_20 "-v rl_post_target_reentry_bars=20 -v rl_post_target_reentry_mode=none"
call :run_arm 05_pt_none_30 "-v rl_post_target_reentry_bars=30 -v rl_post_target_reentry_mode=none"
call :run_arm 06_pt_usma_10_03 "-v rl_post_target_reentry_bars=10 -v rl_post_target_reentry_mode=under_sma_limit -v rl_post_target_under_sma20=0.03"
call :run_arm 07_pt_usma_10_01 "-v rl_post_target_reentry_bars=10 -v rl_post_target_reentry_mode=under_sma_limit -v rl_post_target_under_sma20=0.01"
call :run_arm 08_pt_minstack_10 "-v rl_post_target_reentry_bars=10 -v rl_post_target_reentry_mode=min_stack -v rl_post_target_min_stack=0.05"
call :run_arm 09_pt_stop_10_092 "-v rl_post_target_reentry_bars=10 -v rl_post_target_reentry_mode=stop_loss -v rl_post_target_stop_pct=0.92"
call :run_arm 10_pt_stop_10_095 "-v rl_post_target_reentry_bars=10 -v rl_post_target_reentry_mode=stop_loss -v rl_post_target_stop_pct=0.95"
call :run_arm 11_cd_45 "-v symbol_reentry_cooldown_days=45"
call :run_arm 12_cd_60 "-v symbol_reentry_cooldown_days=60"

echo.
echo === Suite finished: FAIL_COUNT=!FAIL_COUNT! / %TOTAL% ===
echo Summarizing RS_Report + PTQS (HINT=MA,NVDA) under %OUT%\ ...
"%PY%" "%~dp0tools\summarize_rs_post_target_ab.py" --root "%OUT%" --hint-symbols MA,NVDA
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
