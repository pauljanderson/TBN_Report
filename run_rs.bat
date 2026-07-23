@echo off
rem RS (Relative Strength) — SPY_COMPARE 1Y/2Y/3Y > 0 AND IND_TC_*_OUTLOOK all Strong → buy next open.
rem Outputs RS_Closed|Open|Scanner|Summary_<ts>.csv in drive\
rem Standalone: double-click or call from DailyRun.
rem Override before calling:
rem   set RS_SYMBOLS=AAPL,MSFT
rem   set RS_TARGET=1.25
rem   set RS_STOP=0.88
rem TC outlook required: keep use_indicators=true (entry gate, not report-only).
setlocal EnableExtensions
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

if not defined RS_TARGET set "RS_TARGET=1.25"
if not defined RS_STOP set "RS_STOP=0.88"

rem Curated 55 from drive\davey_experiments\spy_tc_strong_system\universe_then_curated\CURATED_SYMBOLS.txt
if not defined RS_SYMBOLS set "RS_SYMBOLS=TRV,WELL,CTAS,CASY,AFL,BDX,CW,CB,BSX,CPRT,AJG,HWM,NVDA,TJX,FISV,PRI,MCD,ATEYY,MCK,POOL,FICO,V,QQQ,ENSG,DHR,UNH,DECK,RELX,RBC,ORLY,MSCI,ROP,CAH,ADBE,BRO,MCO,COST,NFLX,BBIO,POWL,BR,LOGI,TMO,FIX,AER,CHTR,PGR,LII,EME,TDY,ETR,AXSM,SYK,AVGO,WST"

"%PY%" stock_analysis\rocket_rs.py data\newdata\data -o drive -w 8 -v target_pct=%RS_TARGET% -v stop_pct=%RS_STOP% -v use_indicators=true -s "%RS_SYMBOLS%"
exit /b %errorlevel%
