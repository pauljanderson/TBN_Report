@echo off
rem RS A/B — SB-style NO_FT + TIME exits on Relative Strength (RS), RS-scale grid.
rem Does NOT change production run_rs.bat (prod default time_stop_days=252 via RS_TIME_STOP;
rem   this suite still uses BASE time_stop_days=0 / no_ft_days=0 as the control arm).
rem
rem Semantics (portable host knobs; same idea as SB burst_no_ft_days / burst_time_stop_days):
rem   -v no_ft_days=N     sell at close of fill+N if never Close > entry (0=off)
rem   -v time_stop_days=N sell at close after N bars held (0=off; NOT atr_days)
rem Exit priority after stop/target: NO_FT -> TIME -> ATR schedule / other.
rem
rem Default grid (override with env):
rem   NO_FT_GRID=3,5,7,10
rem   TIME_GRID=30,60,90,120,180,252   (RS-scale; prior TIME=5 was wrong timescale)
rem   RUN_COMBO_AUTO=1  — after singles, pick up to MAX_COMBOS promising NO_FT×TIME pairs
rem   MAX_COMBOS=4
rem
rem Arms:
rem   00_control
rem   01_no_ft_<n> ...          (from NO_FT_GRID)
rem   10_time_<n> ...           (from TIME_GRID)
rem   20_combo_nftN_tM ...      (auto after singles when RUN_COMBO_AUTO=1)
rem
rem How to run:
rem   run_rs_noft_time_ab.bat
rem   run_rs_noft_time_ab.bat path\to\universe.csv
rem   set RS_SYMBOLS=AAPL,MSFT & run_rs_noft_time_ab.bat
rem   set NO_FT_GRID=5,10 & set TIME_GRID=90,180 & run_rs_noft_time_ab.bat
rem   set RUN_COMBO_AUTO=0     — singles only
rem   set RS_NOFT_TIME_SMOKE=1 — 00_control only
rem   set SKIP_EXISTING=1      — skip arm if folder already has RS_Audit_Report_*.csv
rem
rem Output:
rem   drive\RS_*_<stamp>.csv
rem   drive\paul_experiments\rs_noft_time_ab\<arm>\
rem   tools\summarize_rs_noft_time_ab.py → comparison.html + comparison.csv
rem
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

if not defined RS_TARGET set "RS_TARGET=1.25"
if not defined RS_STOP set "RS_STOP=0.88"
if not defined RS_WORKERS set "RS_WORKERS=12"
if not defined NO_FT_GRID set "NO_FT_GRID=3,5,7,10"
if not defined TIME_GRID set "TIME_GRID=30,60,90,120,180,252"
if not defined RUN_COMBO_AUTO set "RUN_COMBO_AUTO=1"
if not defined MAX_COMBOS set "MAX_COMBOS=4"
if not defined SKIP_EXISTING set "SKIP_EXISTING=0"

rem Optional leading .csv universe override
set "RS_UNIV_ARG="
if /i "%~x1"==".csv" set "RS_UNIV_ARG=%~f1"
call "%~dp0tools\load_universe_csv.bat" RS "%RS_UNIV_ARG%"
if errorlevel 1 exit /b 1

set "DRIVE_OUT=drive"
set "OUT=drive\paul_experiments\rs_noft_time_ab"
if not exist "%OUT%" mkdir "%OUT%"
rem Production RS levers (match run_rs.bat) + portable exits off on BASE
set "BASE=-v rs_mode=true -v brt_zones=false -v yh_zones=false -v wpbr_zones=false -v rl_mode=false -v target_pct=%RS_TARGET% -v stop_pct=%RS_STOP% -v stop_pct_is_multiplier=true -v use_indicators=true -v indicator_buy=off -v rs_require_tc_strong=true -v growth_filter_enabled=false -v min_spy_compare_1y_at_trigger=0 -v atr_days=0 -v atr_progress=0 -v too_high_multiplier=0 -v rs_max_pct_below_52w_high=0 -v rs_spy_int_tc_not_weak=true -v symbol_reentry_cooldown_days=60 -v no_ft_days=0 -v time_stop_days=0"

set "IDX=0"
set "FAIL_COUNT=0"

echo === RS NO_FT + TIME A/B (RS-scale grid) ===
echo Universe src=%RS_UNIVERSE_SRC% pass_s=%RS_PASS_SYMBOLS%
if "%RS_PASS_SYMBOLS%"=="1" echo Seed: !RS_SYMBOLS!
echo Workers: %RS_WORKERS%
echo NO_FT_GRID=%NO_FT_GRID%
echo TIME_GRID=%TIME_GRID%
echo RUN_COMBO_AUTO=%RUN_COMBO_AUTO% MAX_COMBOS=%MAX_COMBOS% SKIP_EXISTING=%SKIP_EXISTING%
echo Out: %DRIVE_OUT%\  (+ arm copies under %OUT%\^<arm^>)
echo Continues on arm failure; summary at end.
echo.

if /i "%RS_NOFT_TIME_SMOKE%"=="1" (
  call :run_arm 00_control ""
  goto :suite_done
)

rem --- Singles ---
call :run_arm 00_control ""

set "NFT_I=0"
for %%N in (%NO_FT_GRID%) do (
  set /a NFT_I+=1
  if !NFT_I! lss 10 (
    call :run_arm 0!NFT_I!_no_ft_%%N "-v no_ft_days=%%N"
  ) else (
    call :run_arm !NFT_I!_no_ft_%%N "-v no_ft_days=%%N"
  )
)

set "TM_I=10"
for %%T in (%TIME_GRID%) do (
  call :run_arm !TM_I!_time_%%T "-v time_stop_days=%%T"
  set /a TM_I+=1
)

echo.
echo === Singles done — summarizing before optional combos ===
"%PY%" "%~dp0tools\summarize_rs_noft_time_ab.py" --root "%OUT%"
if errorlevel 1 echo WARN: mid-suite summary failed errorlevel=!ERRORLEVEL!

if /i not "%RUN_COMBO_AUTO%"=="1" goto :suite_done

set "COMBO_LIST=%OUT%\combo_queue.txt"
"%PY%" "%~dp0tools\summarize_rs_noft_time_ab.py" --root "%OUT%" --write-combo-list "%COMBO_LIST%" --max-combos %MAX_COMBOS%
if errorlevel 1 (
  echo WARN: combo picker failed — skipping combos
  goto :suite_done
)
if not exist "%COMBO_LIST%" (
  echo No combo queue written — skipping combos
  goto :suite_done
)

echo.
echo === Combo arms from %COMBO_LIST% ===
set "COMBO_I=20"
for /f "usebackq tokens=1,2 delims=," %%A in ("%COMBO_LIST%") do (
  set "CN=%%A"
  set "CT=%%B"
  set "CN=!CN: =!"
  set "CT=!CT: =!"
  if defined CN if defined CT (
    call :run_arm !COMBO_I!_combo_nft!CN!_t!CT! "-v no_ft_days=!CN! -v time_stop_days=!CT!"
    set /a COMBO_I+=1
  )
)

:suite_done
echo.
echo === Suite finished: FAIL_COUNT=!FAIL_COUNT! ===
echo Summarizing under %OUT%\ ...
"%PY%" "%~dp0tools\summarize_rs_noft_time_ab.py" --root "%OUT%"
if errorlevel 1 echo WARN: summary script failed errorlevel=!ERRORLEVEL!
echo.
echo Report: %OUT%\comparison.html
echo CSV:    %OUT%\comparison.csv

if !FAIL_COUNT! gtr 0 exit /b 1
exit /b 0

:run_arm
set "ARM=%~1"
set "EXTRA=%~2"
set /a IDX+=1
echo.
echo ========== [!IDX!] !ARM! ==========
if /i "%SKIP_EXISTING%"=="1" (
  set "_SKIP_AUD="
  for %%F in ("%OUT%\%ARM%\RS_Audit_Report_*.csv") do set "_SKIP_AUD=1"
  if defined _SKIP_AUD (
    echo SKIP !ARM! — already has Audit Report ^(SKIP_EXISTING=1^)
    goto :eof
  )
)
if not exist "%OUT%\%ARM%" mkdir "%OUT%\%ARM%"
if not exist "%DRIVE_OUT%" mkdir "%DRIVE_OUT%"
echo CMD: rocket_tbn --relative-strength BASE + !EXTRA!
if "%RS_PASS_SYMBOLS%"=="1" (
  "%PY%" stock_analysis\rocket_tbn.py data\newdata\data -o "%DRIVE_OUT%" -w %RS_WORKERS% --no-regression --aggressive --relative-strength %BASE% %EXTRA% -s "!RS_SYMBOLS!"
) else (
  "%PY%" stock_analysis\rocket_tbn.py data\newdata\data -o "%DRIVE_OUT%" -w %RS_WORKERS% --no-regression --aggressive --relative-strength %BASE% %EXTRA%
)
set "RC=!ERRORLEVEL!"
if !RC! neq 0 (
  echo WARN errorlevel=!RC! on !ARM! - will still try mirror if RS_* wrote
)
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
if not exist "%OUT%\%ARM%" mkdir "%OUT%\%ARM%"
set "DEST=%OUT%\%ARM%"
echo OK !ARM! stamp=!STAMP! - copying RS_*_!STAMP!.* to !DEST!
(
  echo arm=!ARM!
  echo stamp=!STAMP!
  echo extra=!EXTRA!
) > "!DEST!\STAMP.txt"
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
