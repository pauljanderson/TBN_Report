@echo off
rem Legacy AWK Rocket Launcher audit — outputs RL_* CSVs via portfolio_audit.awk
rem Standalone: double-click or call from DailyRun.
rem Universe: full data\newdata\data\*.csv unless RL_SYMBOLS is set.
rem Extra args (e.g. -AllowRegression) are forwarded to run_audit.ps1.
rem
rem Production RL gates (mirror run_rl.bat): ATR% band off, slope filter off,
rem too_high off, dip_pct 1.055, cut OFF (1000).
rem Exit freeze 2026-09-27: SMA target off, no time clock, sell 80% at +20%,
rem leftover stop at the buy, leftover target +40%.
rem SMA_QUAL=1 is set in run_audit.ps1. Override any RL_* below before calling.
setlocal EnableExtensions
cd /d "%~dp0"

rem Mirror run_rl.bat
if not defined RL_ATR_LOW set "RL_ATR_LOW=off"
if not defined RL_ATR_HIGH set "RL_ATR_HIGH=off"
if not defined RL_SLOPE_THRESHOLD set "RL_SLOPE_THRESHOLD=0"
if not defined RL_TOO_HIGH set "RL_TOO_HIGH=0"
if not defined RL_DIP_PCT set "RL_DIP_PCT=1.055"
if not defined RL_CUT_THE_LOSERS set "RL_CUT_THE_LOSERS=1000"
if not defined RL_EXIT_PERCENT set "RL_EXIT_PERCENT=0"
if not defined RL_EXIT_DAYS set "RL_EXIT_DAYS=0"
if not defined RL_SMA_TARGET_OFF set "RL_SMA_TARGET_OFF=1"
if not defined RL_SCALE_LADDER set "RL_SCALE_LADDER=0.20:0.80:0"
if not defined RL_ENTRY_TARGET_PCT set "RL_ENTRY_TARGET_PCT=0.40"
rem CSV SMA columns are rounded. Compute from closes so AWK matches rocket_rl.py.
if not defined RL_USE_FILE_SMA set "RL_USE_FILE_SMA=0"

if defined RL_SYMBOLS (
  powershell -ExecutionPolicy Bypass -File "run_audit.ps1" %* -s "%RL_SYMBOLS%"
) else (
  powershell -ExecutionPolicy Bypass -File "run_audit.ps1" %*
)
exit /b %ERRORLEVEL%

