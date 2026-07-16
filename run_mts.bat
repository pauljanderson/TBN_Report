@echo off
rem MTS sheet-parity backtest — outputs MTS_Closed|Open|Scanner|Watchlist|Report|Summary_<ts>.csv in drive\
rem Standalone: double-click or call from DailyRun. Override: set MTS_SYMBOLS=SYM1,SYM2 before calling.
rem Keep this list in sync with stock_analysis\mts_universe.py (optimizer / reports).
rem Params: band_pct=0.018 (manual override of optimizer 0.016)
setlocal EnableExtensions
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

if not defined MTS_SYMBOLS set "MTS_SYMBOLS=AAON,ABCB,ABG,ACA,ACU,ALG,AMD,AMN,APP,ARES,ATEYY,AU,BBW,BELFA,BWLP,CF,CHCI,CIEN,CLS,CMC,COHR,COKE,CRS,CRWD,CSTM,CVCO,DDS,DECK,DKL,DKS,DXCM,DY,ENVA,ESP,EVR,FEIM,FN,FRD,FTAI,HWKN,IBP,IESC,IR,JOE,LMAT,LOGI,LRCX,LUGDF,LULU,MATX,MOD,MPWR,MTSI,MTZ,MYRG,NEO,NGL,NTAP,NVDA,NVMI,NXPI,OR,PFSI,PLUS,POOL,POWL,PTC,QXO,RMBS,SANM,SCCO,SGI,SHOP,SIMO,SKYW,TATT,TBBK,TER,TOELY,TPH,TRT,TWLO,UHS,URI,UTI,VSEC,WDAY,WOR,XPO"

"%PY%" stock_analysis\rocket_brt.py data\newdata\data -o drive -w 4 --no-regression --mts-sheet-parity -v band_pct=0.018 -v touch_threshold=2 -v strong_post_pivot_bars=7 -v strong_post_pivot_pct=0.06 -v strong_pre_pivot_bars=7 -v strong_pre_pivot_pct=0.12 -v target_pct=1.22 -v stop_pct=0.934 -v stop_pct_is_multiplier=true -v stop_anchor=signal_low -s "%MTS_SYMBOLS%"
if errorlevel 1 exit /b 1
call "%~dp0run_copy_latest.bat"
exit /b %errorlevel%

