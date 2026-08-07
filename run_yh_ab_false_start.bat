@echo off
rem YH false_start_2022_2023 A/B — Mag9 w/o TSLA (drive\universes\YH_universe.csv).
rem Hypothesis-test: one knob per arm, ≤2 alts per lever (docs/HYPOTHESIS_TEST.md).
rem
rem Prior SPY INT Weak YH AB (full seed, Jul 2026) cited in YH_Deep_Analysis.html —
rem this suite re-runs block on Mag9 + adds missing start_date / growth_bars arms.
rem
rem Arms:
rem   01_control              — frozen run_yh.bat (growth_bars=756 already on)
rem   02_start_2023_01        — entry_start_date=2023-01-01
rem   03_start_2023_10        — entry_start_date=2023-10-01 (2nd start_date alt)
rem   04_spy_block_weak       — Mag9 re-run: spy_int_tc_lag=1 + block_entries_when_spy_int_weak
rem   05_growth_252           — tighter recent-regime proxy (growth_bars=252; slope/regime)
rem
rem Output: drive\paul_experiments\yh_false_start_ab\<arm>\
rem Summary: tools\summarize_yh_pattern_ab.py --suite false_start
rem
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

if not defined YH_WORKERS set "YH_WORKERS=9"
call "%~dp0tools\load_universe_csv.bat" YH
if errorlevel 1 exit /b 1
if not defined YH_SYMBOLS (
  echo ERROR: YH_SYMBOLS empty after universe load
  exit /b 1
)

set "DRIVE_OUT=drive"
set "OUT=drive\paul_experiments\yh_false_start_ab"
set "BASE=-v yh_zones=true -v brt_zones=false -v wpbr_zones=false -v rl_mode=false -v band_pct=0.015 -v yh_move_away_pct=0.03 -v yh_lookback=252 -v yh_memory_mode=sheet -v strong_pre_pivot_bars=7 -v strong_pre_pivot_pct=0.12 -v strong_post_pivot_bars=7 -v strong_post_pivot_pct=0.109 -v strong_pivot_mode=off -v target_pct=1.21 -v stop_pct=0.934 -v stop_pct_is_multiplier=true -v stop_compare_round_decimals=-1 -v too_high_multiplier=0 -v max_spy_compare_1y_at_trigger=0 -v min_spy_compare_1y_at_trigger=0 -v min_atr_pct_at_trigger=0 -v max_atr_pct_at_trigger=0 -v max_market_cap=0 -v min_market_cap=0 -v growth_filter_enabled=true -v growth_bars=756 -v use_indicators=false -v indicator_buy=off -v min_ind_score=0 -v symbol_reentry_cooldown_days=0 -v rl_post_target_reentry_bars=0"

set "TOTAL=5"
set "IDX=0"
set "FAIL_COUNT=0"

echo === YH false_start A/B: %TOTAL% arms ===
echo Seed: %YH_SYMBOLS%
echo Workers: %YH_WORKERS%  Out: %OUT%
echo.

call :run_arm 01_control ""
call :run_arm 02_start_2023_01 "-v start_date=2023-01-01"
call :run_arm 03_start_2023_10 "-v start_date=2023-10-01"
call :run_arm 04_spy_block_weak "-v spy_int_tc_lag=1 -v block_entries_when_spy_int_weak=true -v exit_when_spy_int_turns_weak=false"
call :run_arm 05_growth_252 "-v growth_bars=252"

echo.
echo === Suite finished: FAIL_COUNT=!FAIL_COUNT! / %TOTAL% ===
"%PY%" "%~dp0tools\summarize_yh_pattern_ab.py" --suite false_start --root "%OUT%"
if errorlevel 1 echo WARN: summary script failed errorlevel=!ERRORLEVEL!

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
echo CMD: rocket_tbn YH BASE + !EXTRA!
"%PY%" stock_analysis\rocket_tbn.py data\newdata\data -o "%DRIVE_OUT%" -w %YH_WORKERS% --aggressive --use-duckdb --no-regression %BASE% %EXTRA% -s "%YH_SYMBOLS%"
set "RC=!ERRORLEVEL!"
if !RC! neq 0 (
  echo WARN errorlevel=!RC! on !ARM!
)
set "STAMP="
set "AUD="
for /f "delims=" %%F in ('dir /b /o-d "%DRIVE_OUT%\YH_Audit_Report_*.csv" 2^>nul') do (
  set "AUD=%%F"
  goto :run_arm_got_aud
)
:run_arm_got_aud
if defined AUD (
  for /f "tokens=4 delims=_" %%S in ("!AUD!") do set "STAMP=%%~nS"
)
if not defined STAMP (
  echo FAILED !ARM! - could not detect stamp
  set /a FAIL_COUNT+=1
  goto :eof
)
if not exist "%OUT%\%ARM%" mkdir "%OUT%\%ARM%"
set "DEST=%OUT%\%ARM%"
echo OK !ARM! stamp=!STAMP! - mirroring to !DEST!
set "COPY_COUNT=0"
for %%F in (%DRIVE_OUT%\YH_*_!STAMP!.*) do (
  if exist "%%~F" (
    copy /Y "%%~F" "!DEST!" >nul
    if not errorlevel 1 set /a COPY_COUNT+=1
  )
)
echo stamp=!STAMP!> "!DEST!\STAMP.txt"
echo arm=!ARM!>> "!DEST!\STAMP.txt"
echo extra=!EXTRA!>> "!DEST!\STAMP.txt"
if !COPY_COUNT! equ 0 (
  echo FAILED mirror: zero files for !ARM!
  set /a FAIL_COUNT+=1
) else if !RC! neq 0 (
  echo Mirrored !COPY_COUNT! files ^(despite errorlevel=!RC!^)
  set /a FAIL_COUNT+=1
) else (
  echo Mirrored !COPY_COUNT! files
)
goto :eof
