@echo off
rem Create C:\Users\songg\code and the three target folders.
setlocal EnableExtensions
cd /d "%~dp0"

set "CODE_ROOT=C:\Users\songg\code"
mkdir "%CODE_ROOT%" 2>nul
mkdir "%CODE_ROOT%\TBN" 2>nul
mkdir "%CODE_ROOT%\PredictionsMarkets" 2>nul
mkdir "%CODE_ROOT%\Spotify" 2>nul

echo Created / ensured:
echo   %CODE_ROOT%\TBN
echo   %CODE_ROOT%\PredictionsMarkets
echo   %CODE_ROOT%\Spotify
echo.
echo Next: 02_move_tbn.bat
if not defined REPO_SPLIT_NOPAUSE pause
exit /b 0
