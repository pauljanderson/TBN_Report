echo %time%   
awk -v RL_TRAIL_PROFIT2=.20 -v RL_TRAIL_STOP2=.1 -f stock_analysis/portfolio_audit.awk data\*.csv    1>look.csv
echo %time%   
awk -v RL_TRAIL_PROFIT2=.25 -v RL_TRAIL_STOP2=.15 -f stock_analysis/portfolio_audit.awk data\*.csv    1>look.csv
echo %time%   
awk -v RL_TRAIL_PROFIT2=.3 -v RL_TRAIL_STOP2=.2 -f stock_analysis/portfolio_audit.awk data\*.csv    1>look.csv
echo %time%   
awk -v RL_TRAIL_PROFIT2=.4 -v RL_TRAIL_STOP2=.3 -f stock_analysis/portfolio_audit.awk data\*.csv    1>look.csv
echo %time%   
awk -v RL_TRAIL_PROFIT2=.5 -v RL_TRAIL_STOP2=.4 -f stock_analysis/portfolio_audit.awk data\*.csv    1>look.csv
echo %time%   
awk -v RL_TRAIL_PROFIT2=.6 -v RL_TRAIL_STOP2=.5 -f stock_analysis/portfolio_audit.awk data\*.csv    1>look.csv
echo %time%   




python analyze_rocket.py
equity_drawdown_analysis.png