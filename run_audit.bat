@echo off
rem Legacy AWK Rocket Launcher audit — outputs RL_* CSVs via portfolio_audit.awk
rem Standalone: double-click or call from DailyRun.
rem Override symbols: set RL_SYMBOLS=SYM1,SYM2 before calling (same default as run_rl.bat).
rem Extra args (e.g. -AllowRegression) are forwarded to run_audit.ps1; -s is always from RL_SYMBOLS.
setlocal EnableExtensions
cd /d "%~dp0"

if not defined RL_SYMBOLS set "RL_SYMBOLS=TSLA,AMD,INTC,XOM,LRCX,NFLX,PLTR,KLAC,WFC,ADI,STX,WDC,ANET,APP,TOELY,IBKR,CRWD,ATEYY,NEM,AEM,CNQ,FCX,FTNT,MPWR,MELI,B,FIX,RCL,GM,TER,OKE,OXY,AU,TRGP,DVN,FLEX,CCJ,ARGX,F,CLS,IDXX,EME,GFI,ARES,KGC,ESLT,STLD,MTZ,TECK,WDAY,TWLO,NRG,RMD,FOXA,FTAI,NTRA,FTI,MTSI,TPR,STRL,CFG,FOX,FSLR,ALB,FN,KEY,AKAM,TEAM,BEP,LEN,CRS,RL,DKS,AMKR,NXT"

powershell -ExecutionPolicy Bypass -File "run_audit.ps1" %* -s "%RL_SYMBOLS%"
exit /b %ERRORLEVEL%
