@echo off
REM MUD (Most Up / Most Down) — RESEARCH ONLY. Not wired into DailyRun.
REM Lookback and rebalance are TRADING days (sessions), not calendar days.
REM Default freeze: L=5, R=1 (lean keep from mud_lookback_rebalance_20261005).
setlocal
cd /d "%~dp0"

set LOOKBACK=5
set REBALANCE=1
if not "%~1"=="" set LOOKBACK=%~1
if not "%~2"=="" set REBALANCE=%~2

echo [MUD] research Closed L=%LOOKBACK% R=%REBALANCE% (trading days)
python -u tools\mud_research_closed.py --lookback %LOOKBACK% --rebalance %REBALANCE%
set ERR=%ERRORLEVEL%
if %ERR% neq 0 (
  echo [MUD] FAILED exit %ERR%
  exit /b %ERR%
)
echo [MUD] done — see drive\paul_experiments\mud_system_L%LOOKBACK%_R%REBALANCE%_20261005\ and drive\MUD_LatestRun_Closed.csv
exit /b 0
