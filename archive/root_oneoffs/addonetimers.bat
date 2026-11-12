copy data\newdata\TGS.csv winners
copy data\newdata\HL.csv winners
copy data\newdata\ESEA.csv winners
copy data\newdata\NPO.csv winners
copy data\newdata\TATT.csv winners
copy data\CHCI.csv winners
copy data\ADPT.csv winners
copy data\ASM.csv winners
copy data\BKTI.csv winners
copy data\ADMA.csv winners
copy data\COHR.csv winners
copy data\IBKR.csv winners

awk -f stock_analysis/portfolio_audit.awk winners\*.csv   1>look.csv

del winners\TGS.csv
del winners\HL.csv
del winners\ESEA.csv
del winners\NPO.csv
del winners\TATT.csv
del winners\CHCI.csv
del winners\ADPT.csv
del winners\ASM.csv
del winners\BKTI.csv
del winners\ADMA.csv
del winners\COHR.csv
del winners\IBKR.csv
