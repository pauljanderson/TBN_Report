@echo off
rem Legacy one-liner wrapper. Prefer run_mts.bat (DailyRun / house universe).
setlocal EnableExtensions
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1
"%PY%" "%~dp0stock_analysis\rocket_MTS.py" "%~dp0data\newdata\data" -o "%~dp0drive" --growth-filter -v strong_pre_pivot_bars=8 -v strong_pre_pivot_pct=0.1 -v strong_post_pivot_pct=0.1 -v strong_pivot_mode=both -v displacement_threshold_pct=0 --profile --print-zones -s "AAPL,ABBV,ABT,ACN,ADBE,ADI,AMAT,AMD,AMZN,AU,AVGO,AXP,BABA,BAC,BKR,CDNS,CGC,CI,CRM,CRWD,DIS,GILD,GOOG,GOOGL,HD,JPM,KO,KR,LOW,LYV,META,MPC,MS,MSFT,MU,NEM,NFLX,NVDA,OMER,ORCL,PFE,PG,PLTR,PM,PPTA,SHOP,TMUS,TSLA,TSM,UNH,V,WFC,WMT,XOM"
exit /b %errorlevel%
