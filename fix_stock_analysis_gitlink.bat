@echo off
rem Fix stock_analysis being tracked as a nested git repo (gitlink),
rem so the real .py files (including pygetallMore.py) can be committed and pushed.
rem
rem Run on the OLD machine from the repo root:
rem   fix_stock_analysis_gitlink.bat
rem
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

echo ============================================================
echo  Fix stock_analysis gitlink
echo  Repo: %CD%
echo ============================================================
echo.

if not exist "stock_analysis\" (
  echo ERROR: stock_analysis\ folder not found.
  echo Run this from your stockresearch repo on the OLD machine.
  exit /b 1
)

if not exist "stock_analysis\pygetallMore.py" if not exist "stock_analysis\pyGetAllMore.py" (
  echo ERROR: pygetallMore.py not found inside stock_analysis\
  echo This script must run on the machine that still has the real source files.
  dir /b stock_analysis\*.py 2>nul | more
  exit /b 1
)

echo [1/5] Checking for nested .git inside stock_analysis ...
set "NESTED="
if exist "stock_analysis\.git\" (
  set "NESTED=dir"
  echo       Found nested .git DIRECTORY
) else if exist "stock_analysis\.git" (
  set "NESTED=file"
  echo       Found nested .git FILE
) else (
  echo       No stock_analysis\.git found — OK, continuing
)

if defined NESTED (
  if exist "stock_analysis\.git_nested_backup\" (
    echo ERROR: stock_analysis\.git_nested_backup already exists.
    echo Rename/remove it manually, then re-run.
    exit /b 1
  )
  if exist "stock_analysis\.git_nested_backup" (
    echo ERROR: stock_analysis\.git_nested_backup already exists.
    echo Rename/remove it manually, then re-run.
    exit /b 1
  )
  echo       Moving stock_analysis\.git -^> .git_nested_backup
  move "stock_analysis\.git" "stock_analysis\.git_nested_backup"
  if errorlevel 1 (
    echo ERROR: move failed. Try PowerShell:
    echo   Rename-Item -LiteralPath "stock_analysis\.git" -NewName ".git_nested_backup"
    exit /b 1
  )
  echo       Move OK
) else (
  echo       Nothing to rename
)
echo.

echo [2/5] Removing cached gitlink entry (if present) ...
git rm --cached -f stock_analysis 2>nul
git rm --cached -rf stock_analysis 2>nul
echo       Done
echo.

echo [3/5] Adding stock_analysis as normal files ...
git add stock_analysis/
if errorlevel 1 (
  echo ERROR: git add failed
  exit /b 1
)
echo.

echo [4/5] Verifying pygetallMore is staged ...
git diff --cached --name-only | findstr /i "pygetallMore.py pyGetAllMore.py" >nul
if errorlevel 1 (
  echo.
  echo FAIL: pygetallMore.py is NOT in the staged files.
  echo Git may still be treating stock_analysis as a submodule.
  echo.
  echo Debug:
  git ls-files -s stock_analysis
  echo.
  echo Staged stock_analysis paths:
  git diff --cached --name-only | findstr /i stock_analysis
  exit /b 1
)

echo       OK — pygetallMore.py is staged
echo.
echo       Sample staged files:
git diff --cached --name-only | findstr /i stock_analysis | more
echo.

echo [5/5] Ready to commit + push
echo.
echo Next commands (run these yourself):
echo.
echo   git commit -m "Track stock_analysis source files instead of nested gitlink"
echo   git push
echo.
echo After push succeeds, on the NEW machine:
echo   cd C:\Users\songg\Downloads\stockresearch
echo   git pull
echo   setup_new_pc.bat --smoke
echo.
echo Nested .git backup kept at:
echo   stock_analysis\.git_nested_backup
echo You can delete that backup later after a successful push/pull.
echo ============================================================
exit /b 0
