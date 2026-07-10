@echo off
REM MTS sheet-parity NVDA run (delegates to rocket_brt single codebase)
python "%~dp0stock_analysis\rocket_brt.py" "%~dp0data\newdata\data" -o "%~dp0drive" -s NVDA --mts-sheet-parity --no-equity-metrics --print-zones
