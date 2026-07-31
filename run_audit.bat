@echo off
rem Legacy AWK Rocket Launcher audit — outputs RL_* CSVs via portfolio_audit.awk
rem Standalone: double-click or call from DailyRun.
rem Override symbols: set RL_SYMBOLS=SYM1,SYM2 before calling (same default as run_rl.bat).
rem Extra args (e.g. -AllowRegression) are forwarded to run_audit.ps1; -s is always from RL_SYMBOLS.
rem
rem Production RL gates (mirror run_rl.bat / rocket_brt -v): ATR% band off, slope filter off,
rem too_high off, dip_pct 1.041. SMA_QUAL=1 is set in run_audit.ps1 (rl_sma_qual=1). Override any RL_* below
rem before calling. Direct run_audit.ps1 without these env vars keeps AWK script defaults.
setlocal EnableExtensions
cd /d "%~dp0"

if not defined RL_SYMBOLS set "RL_SYMBOLS=MTZ,NXT,APP,SAIA,NFLX,HUBS,FIVN,AGX,HCI,GHM,MU,AMAT,WRLD,RNG,CF,STX,GLW,LMAT,LMND,DXPE,LMB,EXEL,NGVC,AU,AGI,AA,TGB,PDEX,GFI,UTI,NTRA,STLD,TORXF,DOCN,FN,VLO,INOD,AMD,TTMI,SPRY,BBW,CRWD,TPC,AX,AEHR,ANIP,PSIX,AEM,KINS,MOD,EDVMF,WDC,TGLS,CMCL,CORT,NVAX,AMKR,PATK,ABUS"

rem Mirror run_rl.bat: -v ATR_LOW=off -v ATR_HIGH=off -v rl_slope_threshold=0 -v rl_too_high=0 -v rl_dip_pct=1.041
if not defined RL_ATR_LOW set "RL_ATR_LOW=off"
if not defined RL_ATR_HIGH set "RL_ATR_HIGH=off"
if not defined RL_SLOPE_THRESHOLD set "RL_SLOPE_THRESHOLD=0"
if not defined RL_TOO_HIGH set "RL_TOO_HIGH=0"
if not defined RL_DIP_PCT set "RL_DIP_PCT=1.041"

powershell -ExecutionPolicy Bypass -File "run_audit.ps1" %* -s "%RL_SYMBOLS%"
exit /b %ERRORLEVEL%

