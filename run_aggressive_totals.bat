@echo off
setlocal
cd /d "%~dp0"

if "%~1"=="" (
  echo Usage: run_aggressive_totals.bat RUN_ID [options]
  echo.
  echo Single sweep:
  echo   run_aggressive_totals.bat 260706134400 --engine MTS --avg-positions 7,8,9,10,15
  echo.
  echo Risk grid (36 combos: avg x max_mult x equity_cap x sell):
  echo   run_aggressive_totals.bat 260706134400 --engine MTS --risk-grid -o Drive\aggressive_grid.csv
  exit /b 1
)

python stock_analysis\aggressive_totals.py %*
exit /b %ERRORLEVEL%
