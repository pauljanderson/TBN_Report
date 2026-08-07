@echo off
rem YH post_target_quick_stop A/B — Mag9 w/o TSLA.
rem Prefer post-TARGET-only gates over blanket cooldown alone (ImproveHints).
rem
rem Arms (one coherent lever family; ≤2 post-target alts + blanket contrast):
rem   01_control       — production (cd=0, post_target off)
rem   02_pt_none_15    — rl_post_target_reentry_bars=15 mode=none
rem   03_pt_none_30    — bars=30 mode=none (2nd alt)
rem   04_cd_30         — blanket symbol_reentry_cooldown_days=30 (contrast)
rem
rem Requires zone-path rl_post_target_* wiring in rocket_tbn (YH/BRT/WPBR).
rem Output: drive\paul_experiments\yh_post_target_ab\<arm>\
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
set "OUT=drive\paul_experiments\yh_post_target_ab"
set "BASE=-v yh_zones=true -v brt_zones=false -v wpbr_zones=false -v rl_mode=false -v band_pct=0.015 -v yh_move_away_pct=0.03 -v yh_lookback=252 -v yh_memory_mode=sheet -v strong_pre_pivot_bars=7 -v strong_pre_pivot_pct=0.12 -v strong_post_pivot_bars=7 -v strong_post_pivot_pct=0.109 -v strong_pivot_mode=off -v target_pct=1.21 -v stop_pct=0.934 -v stop_pct_is_multiplier=true -v stop_compare_round_decimals=-1 -v too_high_multiplier=0 -v max_spy_compare_1y_at_trigger=0 -v min_spy_compare_1y_at_trigger=0 -v min_atr_pct_at_trigger=0 -v max_atr_pct_at_trigger=0 -v max_market_cap=0 -v min_market_cap=0 -v growth_filter_enabled=true -v growth_bars=756 -v use_indicators=false -v indicator_buy=off -v min_ind_score=0 -v symbol_reentry_cooldown_days=0 -v rl_post_target_reentry_bars=0"

set "TOTAL=4"
set "IDX=0"
set "FAIL_COUNT=0"

echo === YH post_target A/B: %TOTAL% arms ===
echo Seed: %YH_SYMBOLS%
echo Hint evidence: AAPL,AMD,AMZN,AU,META,NFLX,NVDA (TSLA dropped from universe)
echo.

call :run_arm 01_control ""
call :run_arm 02_pt_none_15 "-v rl_post_target_reentry_bars=15 -v rl_post_target_reentry_mode=none"
call :run_arm 03_pt_none_30 "-v rl_post_target_reentry_bars=30 -v rl_post_target_reentry_mode=none"
call :run_arm 04_cd_30 "-v symbol_reentry_cooldown_days=30"

echo.
echo === Suite finished: FAIL_COUNT=!FAIL_COUNT! / %TOTAL% ===
"%PY%" "%~dp0tools\summarize_yh_pattern_ab.py" --suite post_target --root "%OUT%"
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
"%PY%" stock_analysis\rocket_tbn.py data\newdata\data -o "%DRIVE_OUT%" -w %YH_WORKERS% --aggressive --use-duckdb --no-regression %BASE% %EXTRA% -s "%YH_SYMBOLS%"
set "RC=!ERRORLEVEL!"
if !RC! neq 0 echo WARN errorlevel=!RC! on !ARM!
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
set "DEST=%OUT%\%ARM%"
if not exist "!DEST!" mkdir "!DEST!"
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
echo OK !ARM! stamp=!STAMP! mirrored=!COPY_COUNT!
if !COPY_COUNT! equ 0 set /a FAIL_COUNT+=1
if !RC! neq 0 set /a FAIL_COUNT+=1
goto :eof
