@echo off
setlocal
cd /d "%~dp0"
set "PY=C:\Users\songg\AppData\Local\Programs\Python\Python310\python.exe"
set "MVCP_SYMBOLS=AXON,LULU,CMG,NVDA,TSLA,AMZN,META,NFLX,AMD,AVGO,ANET,CRM,CRWD,NET,SHOP,SNOW,CELH,DECK"
echo === MVCP seed opt A2: time_stop_bars=15 ===
"%PY%" stock_analysis\rocket_tbn.py data\newdata\data -o drive -w 0 --no-regression --aggressive --no-yfinance ^
  -v mvcp_mode=true -v brt_zones=false -v yh_zones=false -v wpbr_zones=false -v rl_mode=false ^
  -v relative_strength_enabled=false -v rs_mode=false -v indicator_buy=off ^
  -v target_pct=1.25 -v stop_pct=0.92 -v stop_pct_is_multiplier=true ^
  -v mvcp_rs_min_percentile=80 -v mvcp_vol_breakout_mult=1.5 -v mvcp_depth_shrink=0.65 ^
  -v mvcp_time_stop_bars=15 -v mvcp_rs_universe=data_dir -v symbol_reentry_cooldown_days=20 ^
  -s "%MVCP_SYMBOLS%"
echo EXIT=%errorlevel%
exit /b %errorlevel%
