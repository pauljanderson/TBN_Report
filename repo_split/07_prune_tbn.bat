@echo off
rem AFTER verify: delete PredictionsMarkets + Spotify owned files from TBN.
rem Does NOT delete report_page_extras.py or resolve_python.bat from TBN.
rem Commits the prune on TBN main locally — you push with git_checkin.bat --push.
setlocal EnableExtensions
cd /d "%~dp0"

set "TBN=C:\Users\songg\code\TBN"
set "PY=python"
where python >nul 2>&1
if errorlevel 1 set "PY=py"

echo === Prune moved systems out of TBN ===
echo This deletes prediction + spotify source files from %TBN%
echo Runtime drive/local/secrets for those systems are NOT auto-deleted.
echo.
set /p "ANS=Type YES to prune: "
if /i not "%ANS%"=="YES" (
  echo Aborted.
if not defined REPO_SPLIT_NOPAUSE pause
  exit /b 1
)

"%PY%" "%~dp0lib\split_copy.py" --prune-from-tbn --tbn "%TBN%"

echo.
echo Optional: commit on TBN
pushd "%TBN%"
git status -sb
echo.
echo When ready:
echo   git_checkin.bat --push -m "Prune PredictionsMarkets and Spotify into their own repos"
popd

echo.
echo Next: 08_verify.bat again, then smoke-test each system.
if not defined REPO_SPLIT_NOPAUSE pause
exit /b 0
