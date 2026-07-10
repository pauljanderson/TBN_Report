@echo off
rem Stage project source code, commit, optionally push.
rem   git_checkin.bat
rem   git_checkin.bat --push
rem   git_checkin.bat -m "describe your changes"
rem   git_checkin.bat --push -m "describe your changes"
rem
rem Stages: .py .bat .ps1 .awk .md .json (settings) scripts/ tools/*.py docs/ .github/
rem Skips: data/, CSV/TSV run outputs, charts, temp debug dirs, optimizer timestamp artifacts.
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "PUSH=0"
set "MSG="

:parse_args
if "%~1"=="" goto args_done
if /i "%~1"=="--push" (
  set "PUSH=1"
  shift
  goto parse_args
)
if /i "%~1"=="-m" (
  set "MSG=%~2"
  shift
  shift
  goto parse_args
)
if /i "%~1"=="--message" (
  set "MSG=%~2"
  shift
  shift
  goto parse_args
)
echo Unknown option: %~1
echo Usage: git_checkin.bat [--push] [-m "message"]
exit /b 1

:args_done
echo === Git check-in: staging source code ===
echo.

rem --- repo metadata ---
git add -- .gitignore .github requirements.txt DUCKDB_SETUP.md 2>nul

rem --- root launchers and libraries ---
git add -- *.bat *.py *.ps1 *.awk *.md 2>nul

rem --- main code tree ---
git add -- stock_analysis/*.py stock_analysis/*.bat stock_analysis/*.awk stock_analysis/*.md 2>nul
git add -- stock_analysis/MTS_Final_Optimized_Settings.json 2>nul
git add -- stock_analysis/MTS_MarkTen_Benchmark.json 2>nul
git add -- stock_analysis/Per_Symbol_Optimized_Settings_Latest.json 2>nul
git add -- stock_analysis/Per_Symbol_Optimized_Settings_Approved_Latest.json 2>nul

rem --- scripts and parity tools ---
git add -- scripts/ 2>nul
git add -- tools/*.py tools/*.md 2>nul

rem --- GitHub Pages ---
git add -- docs/ publish_github_pages.bat 2>nul

rem --- unstage run outputs and temp artifacts if picked up ---
for %%P in (
  "*.csv"
  "*.tsv"
  "*.png"
  "*.jpg"
  "*.xls"
  "*.log"
  "yfinance_cache.json"
  "stock_analysis/Per_Symbol_*_[0-9]*.*"
  "stock_analysis/Per_Symbol_Optimizer_*"
  "stock_analysis/Per_Symbol_All_Runs_*"
  "stock_analysis/Per_Symbol_WF_Folds_*"
  "stock_analysis/Per_Symbol_Param_Value_Counts_*"
  "stock_analysis/MTS_optimizer_progress.json"
  "_*"
  "temp_*"
  "drive_*"
  "spy_probe*"
  ".cursor"
) do git reset HEAD -- %%P 2>nul

echo Staged changes:
git diff --cached --stat
if errorlevel 1 (
  echo No staged changes.
  git status --short
  exit /b 1
)

echo.
git diff --cached --quiet
if not errorlevel 1 (
  echo Nothing to commit.
  exit /b 0
)

if not defined MSG (
  set /p "MSG=Commit message: "
)
if not defined MSG (
  for /f "usebackq delims=" %%T in (`powershell -NoProfile -Command "Get-Date -Format 'yyyy-MM-dd HH:mm'"`) do set "MSG=Code check-in %%T"
)

echo.
echo Committing: !MSG!
git commit -m "!MSG!"
if errorlevel 1 (
  echo Commit failed.
  exit /b 1
)

echo.
git status --short
echo Commit OK.

if "!PUSH!"=="1" (
  echo.
  echo Pushing to remote...
  git push
  if errorlevel 1 (
    echo Push failed.
    exit /b 1
  )
  echo Push OK.
)

exit /b 0
