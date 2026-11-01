@echo off
rem Run at 9:30 ET. Rechecks live buy/sell rules against today's open,
rem writes docs\open_today.html, and pushes that page to GitHub Pages.
rem
rem   run_open_buy_sell.bat
rem
rem Pages URL (about 1-2 minutes after the push):
rem   https://pauljanderson.github.io/TBN_Report/open_today.html

setlocal EnableExtensions
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

"%PY%" -u "%~dp0tools\open_buy_sell_today.py" --push
set RC=%ERRORLEVEL%
echo.
if "%RC%"=="0" (
  echo Page: https://pauljanderson.github.io/TBN_Report/open_today.html
) else (
  echo Open buy/sell page failed. Exit %RC%.
)
exit /b %RC%
