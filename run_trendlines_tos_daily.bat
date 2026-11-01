@echo off

rem Daily Thinkorswim (ToS) trendline study generation for opens + scanner universe (DailyRun step 13d)
rem Runs after run_trendlines_daily.bat (chart creation); writes frozen M/W/D fractal-swing .ts files
rem to a dated stamp folder: drive\paul_studies\trendlines_tos_YYYYMMDD\studies\
rem Also copies .ts files to drive\paul_studies\trendlines_opens_latest\studies\ (shared/latest location).

rem Skip: set SKIP_TRENDLINES_TOS=1

setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0"

if /i "%SKIP_TRENDLINES_TOS%"=="1" (
  echo SKIPPED - run_trendlines_tos_daily ^(SKIP_TRENDLINES_TOS=1^)
  exit /b 0
)
if /i "%SKIP_TRENDLINES%"=="1" (
  echo SKIPPED - run_trendlines_tos_daily ^(SKIP_TRENDLINES=1 implies skip ToS step^)
  exit /b 0
)

set "PY="
if defined PYTHON_EXE set "PY=%PYTHON_EXE%"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
if not defined PY set "PY=python"

rem Build today's date stamp (YYYYMMDD)
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set "TODAY=%%i"

set "STAMP=trendlines_tos_%TODAY%"
set "STAMP_DIR=drive\paul_studies\%STAMP%"
set "LATEST_DIR=drive\paul_studies\trendlines_opens_latest"

echo [trendlines_tos] stamp=%STAMP% stamp-dir=%STAMP_DIR%

rem --- Collect symbol universe (same as trendlines_daily_publish) ---
rem Do not `set /p` this list. set /p keeps only the first 1023 characters of
rem the line. This universe is longer than that and the cut lands on FN, so
rem FNV and every later symbol never reach the generator. Pass the file.
set "UNIV_TMP=%TEMP%\trendlines_tos_univ_%TODAY%.txt"
set "UNIV_ERR=%TEMP%\trendlines_tos_univ_%TODAY%.err"
"%PY%" -c "import sys; sys.path.insert(0,'tools'); from trendlines_opens_universe import collect_opens_universe; from pathlib import Path; syms,_ = collect_opens_universe(Path('drive'), Path('gettarget_positions.csv')); print(','.join(syms))" > "%UNIV_TMP%" 2>"%UNIV_ERR%"
if errorlevel 1 (
  echo ERROR: failed to collect universe
  type "%UNIV_ERR%"
  del "%UNIV_TMP%" 2>nul
  del "%UNIV_ERR%" 2>nul
  exit /b 1
)
for %%A in ("%UNIV_TMP%") do set "UNIV_BYTES=%%~zA"
if "%UNIV_BYTES%"=="0" (
  echo ERROR: empty symbol list from trendlines_opens_universe
  type "%UNIV_ERR%"
  del "%UNIV_TMP%" 2>nul
  del "%UNIV_ERR%" 2>nul
  exit /b 1
)
echo [trendlines_tos] universe file: %UNIV_TMP% ^(%UNIV_BYTES% bytes^)

rem --- Generate ToS .ts files into dated stamp folder ---
"%PY%" tools\gen_trendlines_tos_studies.py ^
  --symbols-file "%UNIV_TMP%" ^
  --stamp "%STAMP%" ^
  --stamp-dir "%STAMP_DIR%"
if errorlevel 1 (
  echo ERROR: gen_trendlines_tos_studies.py failed
  del "%UNIV_TMP%" 2>nul
  del "%UNIV_ERR%" 2>nul
  exit /b 1
)
del "%UNIV_TMP%" 2>nul
del "%UNIV_ERR%" 2>nul

rem --- Copy/sync .ts files to trendlines_opens_latest\studies\ ---
if not exist "%LATEST_DIR%\studies" mkdir "%LATEST_DIR%\studies"
xcopy /Y /I "%STAMP_DIR%\studies\*.ts" "%LATEST_DIR%\studies\" > nul 2>&1

rem --- Copy index.html and README.md to latest folder ---
if exist "%STAMP_DIR%\index.html"  copy /Y "%STAMP_DIR%\index.html"  "%LATEST_DIR%\tos_index.html"  > nul 2>&1
if exist "%STAMP_DIR%\README.md"   copy /Y "%STAMP_DIR%\README.md"   "%LATEST_DIR%\tos_README.md"   > nul 2>&1
if exist "%STAMP_DIR%\segments.json" copy /Y "%STAMP_DIR%\segments.json" "%LATEST_DIR%\tos_segments.json" > nul 2>&1

echo [trendlines_tos] Done — %STAMP_DIR%\studies\
exit /b 0
