@echo off
rem StockBee Momentum Burst A/B: Market Monitor breadth + 2Lynch T-1 narrow/down.
rem Does NOT change production run_sb.bat / run_stockbee_burst.bat defaults.
rem Root alias: SB_MM_2Lynch_ab.bat (preferred one-liner for custom universe).
rem
rem Spec: drive\paul_experiments\tbn_new_systems\stockbee_momentum_burst\SB_NEXT_BUILDS.md
rem   MM: allow signal iff mm_ratio[T-1] >= burst_mm_min_ratio (lag-1; no fill re-check)
rem   2Lynch N: require T-1 narrow OR down (burst_require_t1_narrow_or_down)
rem
rem EDIT SETTINGS: change MM_RATIO_* / RUN_* flags in the "EDIT DEFAULTS HERE" block
rem   below — save, then run. Env override still works if already set.
rem
rem Arms (thresholds from settings block):
rem   00_control              — current SB; both new gates OFF
rem   01_mm_soft              — MM only, burst_mm_min_ratio=MM_RATIO_SOFT (default 1.5)
rem   02_mm_default           — MM only, burst_mm_min_ratio=MM_RATIO (default 2.0)
rem   03_mm_tight             — MM only, burst_mm_min_ratio=MM_RATIO_TIGHT (default 3.0)
rem   04_t1_n                 — 2Lynch T-1 N only
rem   05_mm_default_and_t1_n  — MM@MM_RATIO + T-1 N
rem   06_mm_soft_and_t1_n     — MM@MM_RATIO_SOFT + T-1 N
rem
rem Universe (first match wins):
rem   -s / --symbol LIST   e.g. SB_MM_2Lynch_ab.bat -s HROW,REAL,AKR
rem   %%1 comma list       e.g. SB_MM_2Lynch_ab.bat HROW,REAL,AKR
rem   %%1 path to GOLD-style csv (one line of tickers)
rem   SB_SYMBOLS env       (or uncomment set in settings block)
rem   else GOLD_UNIVERSE.csv
rem
rem How to run:
rem   SB_MM_2Lynch_ab.bat
rem   SB_MM_2Lynch_ab.bat HROW,REAL,AKR
rem   SB_MM_2Lynch_ab.bat -s HROW,REAL,AKR
rem   run_sb_ab_mm_2lynch.bat
rem   (optional) set SB_MM_SMOKE=1  — run 00_control only
rem   (optional) set SB_MM_RESOLVE_ONLY=1 — universe + Gates echo, no arms
rem   (optional) set MM_FORCE_REBUILD=true — rebuild drive\SB_MM_Series_latest.csv
rem
rem Output:
rem   - Primary: drive\SB_*_<stamp>.csv
rem   - Copies:  drive\paul_experiments\tbn_new_systems\stockbee_momentum_burst\ab_mm_2lynch\<arm>\
rem After suite: tools\summarize_sb_mm_2lynch_ab.py writes HTML+MD comparison.
rem
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

rem === EDIT DEFAULTS HERE (open this file, change values, save, run) ===
rem Env already set before call still wins (if not defined).
if not defined MM_RATIO_SOFT set "MM_RATIO_SOFT=1.5"
if not defined MM_RATIO set "MM_RATIO=2.0"
if not defined MM_RATIO_TIGHT set "MM_RATIO_TIGHT=3.0"
if not defined T1_NARROW_MODE set "T1_NARROW_MODE=median"
if not defined MM_FORCE_REBUILD set "MM_FORCE_REBUILD=false"
if not defined SB_WORKERS set "SB_WORKERS=0"
if not defined SB_AGGRESSIVE set "SB_AGGRESSIVE=true"
rem Toggle arms (1/true = run). Control always runs unless smoke/resolve-only.
if not defined RUN_MM_SOFT set "RUN_MM_SOFT=1"
if not defined RUN_MM_DEFAULT set "RUN_MM_DEFAULT=1"
if not defined RUN_MM_TIGHT set "RUN_MM_TIGHT=1"
if not defined RUN_T1_N set "RUN_T1_N=1"
if not defined RUN_MM_DEFAULT_AND_T1 set "RUN_MM_DEFAULT_AND_T1=1"
if not defined RUN_MM_SOFT_AND_T1 set "RUN_MM_SOFT_AND_T1=1"
rem if not defined SB_SYMBOLS set "SB_SYMBOLS=HROW,REAL,AKR"
rem === end defaults ===

set "DRIVE_OUT=drive"
set "OUT=drive\paul_experiments\tbn_new_systems\stockbee_momentum_burst\ab_mm_2lynch"
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
  echo Example: SB_MM_2Lynch_ab.bat -s HROW,REAL,AKR
  echo Example: SB_MM_2Lynch_ab.bat -s "HROW,REAL,AKR"
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
echo Use: SB_MM_2Lynch_ab.bat -s HROW,REAL,AKR   or   SB_MM_2Lynch_ab.bat "HROW,REAL,AKR"
exit /b 1

:univ_ok
set "SB_UNIV_FILE=%TEMP%\sb_mm_universe_%RANDOM%%RANDOM%.csv"
> "!SB_UNIV_FILE!" echo !SB_SYMBOLS!
set /p SB_SYMBOLS=<"!SB_UNIV_FILE!"
if not defined SB_SYMBOLS (
  echo ERROR: failed to materialize universe file "!SB_UNIV_FILE!"
  exit /b 1
)
echo [SB AB] Universe file: !SB_UNIV_FILE!
echo [SB AB] Symbols: !SB_SYMBOLS!
echo [SB AB] Workers=%SB_WORKERS%  Out=%DRIVE_OUT%\  (+ arm copies under %OUT%\^<arm^>)
echo [SB AB] Gates: mm_soft=!MM_RATIO_SOFT!  mm=!MM_RATIO!  mm_tight=!MM_RATIO_TIGHT!  t1_mode=!T1_NARROW_MODE!
if /i "%SB_MM_RESOLVE_ONLY%"=="1" (
  echo [SB AB] SB_MM_RESOLVE_ONLY=1 — universe OK, exiting before arms
  if exist "!SB_UNIV_FILE!" del /q "!SB_UNIV_FILE!" >nul 2>&1
  exit /b 0
)
if /i "%SB_MM_SMOKE%"=="1" echo [SB AB] SB_MM_SMOKE=1 — running 00_control only
if /i "%SB_MM_SMOKE%"=="true" echo [SB AB] SB_MM_SMOKE=true — running 00_control only
echo.

set "TOTAL=0"
set "IDX=0"
set "FAIL_COUNT=0"
set "STAMPS_SEEN="

if /i "%SB_MM_SMOKE%"=="1" goto :smoke_one_arm
if /i "%SB_MM_SMOKE%"=="true" goto :smoke_one_arm

rem Pre-count arms for progress display
set /a TOTAL+=1
if /i "%RUN_MM_SOFT%"=="1" set /a TOTAL+=1
if /i "%RUN_MM_SOFT%"=="true" set /a TOTAL+=1
if /i "%RUN_MM_DEFAULT%"=="1" set /a TOTAL+=1
if /i "%RUN_MM_DEFAULT%"=="true" set /a TOTAL+=1
if /i "%RUN_MM_TIGHT%"=="1" set /a TOTAL+=1
if /i "%RUN_MM_TIGHT%"=="true" set /a TOTAL+=1
if /i "%RUN_T1_N%"=="1" set /a TOTAL+=1
if /i "%RUN_T1_N%"=="true" set /a TOTAL+=1
if /i "%RUN_MM_DEFAULT_AND_T1%"=="1" set /a TOTAL+=1
if /i "%RUN_MM_DEFAULT_AND_T1%"=="true" set /a TOTAL+=1
if /i "%RUN_MM_SOFT_AND_T1%"=="1" set /a TOTAL+=1
if /i "%RUN_MM_SOFT_AND_T1%"=="true" set /a TOTAL+=1

call :run_arm 00_control ""
if /i "%RUN_MM_SOFT%"=="1" call :run_arm 01_mm_soft "-v burst_mm_gate=true -v burst_mm_min_ratio=!MM_RATIO_SOFT! -v mm_force_rebuild=!MM_FORCE_REBUILD!"
if /i "%RUN_MM_SOFT%"=="true" call :run_arm 01_mm_soft "-v burst_mm_gate=true -v burst_mm_min_ratio=!MM_RATIO_SOFT! -v mm_force_rebuild=!MM_FORCE_REBUILD!"
if /i "%RUN_MM_DEFAULT%"=="1" call :run_arm 02_mm_default "-v burst_mm_gate=true -v burst_mm_min_ratio=!MM_RATIO! -v mm_force_rebuild=false"
if /i "%RUN_MM_DEFAULT%"=="true" call :run_arm 02_mm_default "-v burst_mm_gate=true -v burst_mm_min_ratio=!MM_RATIO! -v mm_force_rebuild=false"
if /i "%RUN_MM_TIGHT%"=="1" call :run_arm 03_mm_tight "-v burst_mm_gate=true -v burst_mm_min_ratio=!MM_RATIO_TIGHT! -v mm_force_rebuild=false"
if /i "%RUN_MM_TIGHT%"=="true" call :run_arm 03_mm_tight "-v burst_mm_gate=true -v burst_mm_min_ratio=!MM_RATIO_TIGHT! -v mm_force_rebuild=false"
if /i "%RUN_T1_N%"=="1" call :run_arm 04_t1_n "-v burst_require_t1_narrow_or_down=true -v burst_t1_narrow_mode=!T1_NARROW_MODE!"
if /i "%RUN_T1_N%"=="true" call :run_arm 04_t1_n "-v burst_require_t1_narrow_or_down=true -v burst_t1_narrow_mode=!T1_NARROW_MODE!"
if /i "%RUN_MM_DEFAULT_AND_T1%"=="1" call :run_arm 05_mm_default_and_t1_n "-v burst_mm_gate=true -v burst_mm_min_ratio=!MM_RATIO! -v burst_require_t1_narrow_or_down=true -v burst_t1_narrow_mode=!T1_NARROW_MODE! -v mm_force_rebuild=false"
if /i "%RUN_MM_DEFAULT_AND_T1%"=="true" call :run_arm 05_mm_default_and_t1_n "-v burst_mm_gate=true -v burst_mm_min_ratio=!MM_RATIO! -v burst_require_t1_narrow_or_down=true -v burst_t1_narrow_mode=!T1_NARROW_MODE! -v mm_force_rebuild=false"
if /i "%RUN_MM_SOFT_AND_T1%"=="1" call :run_arm 06_mm_soft_and_t1_n "-v burst_mm_gate=true -v burst_mm_min_ratio=!MM_RATIO_SOFT! -v burst_require_t1_narrow_or_down=true -v burst_t1_narrow_mode=!T1_NARROW_MODE! -v mm_force_rebuild=false"
if /i "%RUN_MM_SOFT_AND_T1%"=="true" call :run_arm 06_mm_soft_and_t1_n "-v burst_mm_gate=true -v burst_mm_min_ratio=!MM_RATIO_SOFT! -v burst_require_t1_narrow_or_down=true -v burst_t1_narrow_mode=!T1_NARROW_MODE! -v mm_force_rebuild=false"
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
if /i "%SB_MM_SMOKE%"=="1" goto :skip_summary
if /i "%SB_MM_SMOKE%"=="true" goto :skip_summary
if !FAIL_COUNT! gtr 0 (
  echo FAIL: one or more arms failed — skipping summarize ^(no stale comparison^)
  goto :exit_rc
)
echo Summarizing under %OUT%\ ...
"%PY%" "%~dp0tools\summarize_sb_mm_2lynch_ab.py" --root "%OUT%"
if errorlevel 1 echo WARN: summary script failed errorlevel=!ERRORLEVEL!
echo.
echo Docs: %OUT%\README.md  and  %OUT%\comparison.html
echo Re-run: SB_MM_2Lynch_ab.bat   ^(or run_sb_ab_mm_2lynch.bat^)
goto :exit_rc

:skip_summary
echo [SB AB] Smoke mode — skipped summarize_sb_mm_2lynch_ab.py
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
