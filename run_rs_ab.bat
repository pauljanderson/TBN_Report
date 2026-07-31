set OUT=drive\paul_experiments\rs_fat_stops_ab
set SEED=AAPL,NVDA,GOOGL,MSFT,AMZN,TSM,AVGO,META,LLY,JPM,WMT,MU,AMD,V,XOM,ASML,MA
set BASE=-v rs_mode=true -v brt_zones=false -v yh_zones=false -v wpbr_zones=false -v rl_mode=false -v target_pct=1.25 -v stop_pct_is_multiplier=true -v use_indicators=true -v indicator_buy=off -v rs_require_tc_strong=true -v growth_filter_enabled=false -v min_spy_compare_1y_at_trigger=0 -v atr_days=0 -v too_high_multiplier=0 -v rs_max_pct_below_52w_high=0 -v rs_spy_int_tc_not_weak=false

rem per arm: -o %OUT%\<arm>  + arm -v  + -s %SEED%
rem python stock_analysis\rocket_tbn.py data\newdata\data -w 17 --no-regression --aggressive --relative-strength %BASE% -v stop_pct=0.89 -s "%SEED%"
rem python stock_analysis\rocket_tbn.py data\newdata\data -w 17 --no-regression --aggressive --relative-strength %BASE% -v stop_pct=0.91 -s "%SEED%"
rem python stock_analysis\rocket_tbn.py data\newdata\data -w 17 --no-regression --aggressive --relative-strength %BASE% -v stop_pct=0.92 -s "%SEED%"
rem python stock_analysis\rocket_tbn.py data\newdata\data -w 17 --no-regression --aggressive --relative-strength %BASE% -v stop_pct=0.88 -v sell_breakdown=breakdown_plus -s "%SEED%"
python stock_analysis\rocket_tbn.py data\newdata\data -w 17 --no-regression --aggressive --relative-strength %BASE% -v stop_pct=0.88 -v sma_stop_days=35 -s "%SEED%"
python stock_analysis\rocket_tbn.py data\newdata\data -w 17 --no-regression --aggressive --relative-strength %BASE% -v stop_pct=0.88 -v sma_stop_days=40 -s "%SEED%"
python stock_analysis\rocket_tbn.py data\newdata\data -w 17 --no-regression --aggressive --relative-strength %BASE% -v stop_pct=0.88 -v sma_stop_days=45 -s "%SEED%"
python stock_analysis\rocket_tbn.py data\newdata\data -w 17 --no-regression --aggressive --relative-strength %BASE% -v stop_pct=0.88 -v sma_stop_days=50 -s "%SEED%"
python stock_analysis\rocket_tbn.py data\newdata\data -w 17 --no-regression --aggressive --relative-strength %BASE% -v stop_pct=0.88 -v sma_stop_days=55 -s "%SEED%"
