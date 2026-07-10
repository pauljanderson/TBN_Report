@echo off
rem Shared symbol lists and defaults for DailyRun and run_*.bat scripts.
rem Call from DailyRun.bat (or set env vars before calling a single engine).
rem Do not use setlocal here — values must persist for the caller.

if not defined RL_SYMBOLS set "RL_SYMBOLS=TSLA,AMD,INTC,XOM,LRCX,NFLX,PLTR,KLAC,WFC,ADI,STX,WDC,ANET,APP,TOELY,IBKR,CRWD,ATEYY,NEM,AEM,CNQ,FCX,FTNT,MPWR,MELI,B,FIX,RCL,GM,TER,OKE,OXY,AU,TRGP,DVN,FLEX,CCJ,ARGX,F,CLS,IDXX,EME,GFI,ARES,KGC,ESLT,STLD,MTZ,TECK,WDAY,TWLO,NRG,RMD,FOXA,FTAI,NTRA,FTI,MTSI,TPR,STRL,CFG,FOX,FSLR,ALB,FN,KEY,AKAM,TEAM,BEP,LEN,CRS,RL,DKS,AMKR,NXT"

if not defined BRT_SYMBOLS set "BRT_SYMBOLS=AAPL,ABBV,ACN,ADBE,ADI,AMAT,AMD,AMZN,AU,AVGO,AXP,BABA,BAC,CDNS,CI,CRM,CRWD,DIS,GILD,GOOG,GOOGL,HD,JPM,KO,KR,LOW,LYV,META,MPC,MS,MSFT,MU,NEM,NFLX,NVDA,OMER,ORCL,PFE,PG,PLTR,PM,PPTA,SHOP,TMUS,TSLA,TSM,UNH,V,WFC,WMT,XOM"

if not defined PER_SYMBOL_SETTINGS set "PER_SYMBOL_SETTINGS=stock_analysis\Per_Symbol_Optimized_Settings_Approved_Latest.json"

rem Exploratory (all optimizer candidates, not adoption-filtered):
rem   set "PER_SYMBOL_SETTINGS=stock_analysis\Per_Symbol_Optimized_Settings_Latest.json"

exit /b 0
