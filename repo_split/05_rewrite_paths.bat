@echo off
rem Replace C:\Users\songg\Downloads\stockresearch with each repo's new root.
rem Also forces DailyRun.bat to cd /d "%~dp0" and slims TBN git_pull.bat.
setlocal EnableExtensions
cd /d "%~dp0"

set "TBN=C:\Users\songg\code\TBN"
set "PM=C:\Users\songg\code\PredictionsMarkets"
set "SPOTIFY=C:\Users\songg\code\Spotify"
set "PY=python"
where python >nul 2>&1
if errorlevel 1 set "PY=py"

echo === Rewrite hardcoded paths ===
"%PY%" "%~dp0lib\rewrite_paths.py" --root "%TBN%" --new-root "%TBN%"
"%PY%" "%~dp0lib\rewrite_paths.py" --root "%PM%" --new-root "%PM%"
"%PY%" "%~dp0lib\rewrite_paths.py" --root "%SPOTIFY%" --new-root "%SPOTIFY%"

echo.
echo Audit leftovers in TBN:
"%PY%" "%~dp0lib\rewrite_paths.py" --root "%TBN%" --audit-only
echo.
echo Next: 06_github_remotes.bat
if not defined REPO_SPLIT_NOPAUSE pause
exit /b 0
