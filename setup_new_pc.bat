@echo off
rem First-time setup on a new Windows PC (clone, Python, pip, path/data checks).
rem
rem From an existing clone:
rem   setup_new_pc.bat
rem   setup_new_pc.bat --smoke
rem
rem Clone fresh (requires git on PATH):
rem   setup_new_pc.bat --clone "C:\Users\songg\Downloads\stockresearch"
rem   setup_new_pc.bat --clone "D:\stockresearch" --smoke
rem
rem Optional: copy data\ from old laptop/USB before --smoke, or run run_backfill_data_to_2010.bat after.
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "CLONE_DIR="
set "SMOKE=0"
set "REPO_URL=https://github.com/pauljanderson/TBN_Report.git"
set "RECOMMENDED_ROOT=C:\Users\songg\Downloads\stockresearch"
set "FAIL=0"

:parse_args
if "%~1"=="" goto args_done
if /i "%~1"=="--clone" (
  set "CLONE_DIR=%~2"
  shift
  shift
  goto parse_args
)
if /i "%~1"=="--smoke" (
  set "SMOKE=1"
  shift
  goto parse_args
)
if /i "%~1"=="--repo" (
  set "REPO_URL=%~2"
  shift
  shift
  goto parse_args
)
echo Unknown option: %~1
echo Usage: setup_new_pc.bat [--clone "C:\path\to\stockresearch"] [--smoke] [--repo URL]
exit /b 1

:args_done
if defined CLONE_DIR goto do_clone
goto setup_here

:do_clone
if exist "%CLONE_DIR%\.git" (
  echo Repo already exists: %CLONE_DIR%
  cd /d "%CLONE_DIR%"
  goto setup_here
)
echo Cloning %REPO_URL%
echo   into %CLONE_DIR%
git clone "%REPO_URL%" "%CLONE_DIR%"
if errorlevel 1 (
  echo ERROR: git clone failed. Install Git and retry.
  exit /b 1
)
cd /d "%CLONE_DIR%"
echo.

:setup_here
echo ============================================================
echo  Stockresearch setup — %CD%
echo ============================================================
echo.

rem --- 1) Git ---
where git >nul 2>&1
if errorlevel 1 (
  echo [WARN] git not on PATH. Install Git for Windows.
  set "FAIL=1"
) else (
  for /f "delims=" %%V in ('git --version 2^>nul') do echo [OK] %%V
  git rev-parse --is-inside-work-tree >nul 2>&1
  if errorlevel 1 (
    echo [WARN] Current folder is not a git repo.
    set "FAIL=1"
  ) else (
    for /f "delims=" %%B in ('git branch --show-current 2^>nul') do echo [OK] Branch: %%B
    git status -sb 2>nul | findstr /r "ahead" >nul
    if not errorlevel 1 echo [INFO] Local branch is ahead of remote — run: git push
    git status -sb 2>nul | findstr /r "behind" >nul
    if not errorlevel 1 echo [INFO] Remote has new commits — run: git pull
  )
)
echo.

rem --- 2) Python ---
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 (
  echo [FAIL] Python not found.
  echo        Install: winget install -e --id Python.Python.3.10 --scope user
  echo        Or download from https://www.python.org/downloads/
  set "FAIL=1"
  goto skip_pip
)
for /f "delims=" %%V in ('"%PY%" --version 2^>^&1') do echo [OK] Python: %%V at %PY%

echo.
echo Installing Python packages from requirements.txt ...
"%PY%" -m pip install --upgrade pip
if errorlevel 1 set "FAIL=1"
"%PY%" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
  echo [FAIL] pip install failed.
  set "FAIL=1"
) else (
  "%PY%" -c "import pandas, yfinance, duckdb, numpy; print('[OK] imports: pandas, yfinance, duckdb, numpy')"
  if errorlevel 1 (
    echo [FAIL] Package import check failed.
    set "FAIL=1"
  )
)

:skip_pip
echo.

rem --- 3) Path audit (hardcoded laptop paths) ---
echo Checking for hardcoded paths (C:\Users\songg\...) ...
set "HARDCODED=0"
for /f "delims=" %%F in ('findstr /s /i /m /c:"C:\Users\songg" "%~dp0*.py" "%~dp0*.bat" 2^>nul') do (
  echo %%F | findstr /i "\\\.git\\ \\__pycache__\\ \\\.cursor\\" >nul
  if errorlevel 1 (
    echo   [PATH] %%F
    set "HARDCODED=1"
  )
)
if "!HARDCODED!"=="0" (
  echo [OK] No C:\Users\songg hardcoded paths found.
) else (
  echo [WARN] Files above embed the old laptop path.
  echo        Easiest fix: clone to %RECOMMENDED_ROOT%
  echo        Or search/replace C:\Users\songg\Downloads\stockresearch with this folder.
)
echo.

rem --- 4) Project root match ---
echo %CD% | findstr /i /c:"%RECOMMENDED_ROOT%" >nul
if errorlevel 1 (
  echo [WARN] Repo is not at recommended path:
  echo        %RECOMMENDED_ROOT%
  echo        Current: %CD%
) else (
  echo [OK] Repo path matches recommended location.
)
echo.

rem --- 5) Data and config ---
set "DATA_CSV=%~dp0data\newdata\data"
set "DATA_DB=%~dp0data\ohlcv.duckdb"
set "DRIVE_DIR=%~dp0drive"
set "DRIVE_DIR2=%~dp0Drive"
set "APPROVED=%~dp0stock_analysis\Per_Symbol_Optimized_Settings_Approved_Latest.json"

if exist "%DATA_CSV%\NVDA.csv" (
  echo [OK] NVDA.csv exists
  if defined PY (
    set "NVDA_FILE=%DATA_CSV%\NVDA.csv"
    "%PY%" -c "import os,pandas as pd; df=pd.read_csv(os.environ['NVDA_FILE'], index_col=0); print('      rows:', len(df), 'start:', df.index.min())"
  )
) else (
  echo [WARN] Missing %DATA_CSV%\NVDA.csv
  echo        Copy data\ from old laptop, or run: run_backfill_data_to_2010.bat
  set "FAIL=1"
)

if exist "%DATA_DB%" (
  echo [OK] DuckDB: data\ohlcv.duckdb
) else (
  echo [INFO] DuckDB not found — optional. Build with:
  echo        python scripts\build_ohlcv_duckdb.py --data-dir data\newdata\data --db-path data\ohlcv.duckdb --replace
)

if exist "%APPROVED%" (
  echo [OK] Per-symbol approved settings present
) else (
  echo [INFO] No Approved per-symbol settings yet — run per-symbol optimizer or copy from old laptop.
)

if exist "%DRIVE_DIR%\last_run_ts.txt" (
  echo [OK] Local drive\ output folder in use
) else if exist "%DRIVE_DIR2%\last_run_ts.txt" (
  echo [OK] Local Drive\ output folder in use
) else (
  echo [INFO] No drive\last_run_ts.txt yet — normal before first DailyRun.
  echo        Ensure Google Drive syncs your output folder, or create drive\ under repo root.
)
echo.

rem --- 6) Optional smoke test ---
if not "%SMOKE%"=="1" goto finish
if not defined PY goto finish
echo Smoke test: pygetallMore import + START_DATE ...
"%PY%" -c "import sys; sys.path.insert(0, r'%~dp0stock_analysis'); from pygetallMore import START_DATE, DATA_DIR; print('[OK] START_DATE=', START_DATE); print('[OK] DATA_DIR=', DATA_DIR)"
if errorlevel 1 (
  echo [FAIL] pygetallMore import failed.
  set "FAIL=1"
)
echo.

:finish
echo ============================================================
if "%FAIL%"=="1" (
  echo  Setup incomplete — fix items marked FAIL/WARN above.
  echo  See SETUP_NEW_PC.md for full migration steps.
  exit /b 1
)
echo  Setup checks passed.
echo  Next: run DailyRun.bat once manually, then recreate Task Scheduler.
echo  Docs: SETUP_NEW_PC.md
echo ============================================================
exit /b 0
