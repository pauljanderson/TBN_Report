@echo off
rem Python Rocket Launcher (rl_mode=true) — outputs RL_Closed|Open|... in drive\
rem Standalone: double-click or call from DailyRun. Override: set RL_SYMBOLS=SYM1,SYM2 before calling.
rem IND_TC_*: not on RL_Closed yet (separate writer; indicators only for mandatory/exclude gates).
setlocal EnableExtensions
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

if not defined RL_SYMBOLS set "RL_SYMBOLS=TSLA,AMD,INTC,XOM,LRCX,NFLX,PLTR,KLAC,WFC,ADI,STX,WDC,ANET,APP,TOELY,IBKR,CRWD,ATEYY,NEM,AEM,CNQ,FCX,FTNT,MPWR,MELI,B,FIX,RCL,GM,TER,OKE,OXY,AU,TRGP,DVN,FLEX,CCJ,ARGX,F,CLS,IDXX,EME,GFI,ARES,KGC,ESLT,STLD,MTZ,TECK,WDAY,TWLO,NRG,RMD,FOXA,FTAI,NTRA,FTI,MTSI,TPR,STRL,CFG,FOX,FSLR,ALB,FN,KEY,AKAM,TEAM,BEP,LEN,CRS,RL,DKS,AMKR,NXT"
if not defined PER_SYMBOL_SETTINGS set "PER_SYMBOL_SETTINGS=stock_analysis\Per_Symbol_Optimized_Settings_Approved_Latest.json"

set "PS_ARGS="
if exist "%~dp0%PER_SYMBOL_SETTINGS%" set "PS_ARGS=--per-symbol-settings %PER_SYMBOL_SETTINGS%"
"%PY%" stock_analysis\rocket_brt.py data\newdata\data -o drive -w 5 --no-regression -v rl_mode=true -v brt_zones=false -v yh_zones=false -v indicator_buy=off %PS_ARGS% -s "%RL_SYMBOLS%"
exit /b %errorlevel%
