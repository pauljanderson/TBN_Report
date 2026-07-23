@echo off
rem Live stop/target for active systems. IND is deprecated and excluded from scheduled targets.
rem Standalone: double-click or call from DailyRun.
setlocal EnableExtensions
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

if not defined PER_SYMBOL_SETTINGS set "PER_SYMBOL_SETTINGS=stock_analysis\Per_Symbol_Optimized_Settings_Approved_Latest.json"

set "PS_ARGS="
if exist "%~dp0%PER_SYMBOL_SETTINGS%" set "PS_ARGS=--per-symbol-settings %PER_SYMBOL_SETTINGS%"
"%PY%" "%~dp0getTarget.py" ^
  --exclude-system=IND ^
  --brt-atr-target=0 ^
  --brt-atr-stop=0 ^
  --brt-atr-increment=0 ^
  --brt-atr-progress=0 ^
  --brt-atr-days=0 ^
  "--brt-target-pct=1.21" ^
  "--brt-stop-pct=0.934" ^
  --ind-atr-target=2.0 ^
  --ind-atr-stop=1.2 ^
  --ind-atr-increment=0 ^
  --ind-atr-progress=0 ^
  --ind-atr-days=0 ^
  "--ind-target-pct=1.21" ^
  "--ind-stop-pct=0.903" ^
  --yh-atr-target=0 ^
  --yh-atr-stop=0 ^
  --yh-atr-increment=0 ^
  --yh-atr-progress=0 ^
  --yh-atr-days=0 ^
  "--yh-target-pct=1.27" ^
  "--yh-stop-pct=0.923" ^
  --mts-atr-target=0 ^
  --mts-atr-stop=0 ^
  --mts-atr-increment=0 ^
  --mts-atr-progress=0 ^
  --mts-atr-days=0 ^
  "--mts-target-pct=1.22" ^
  "--mts-stop-pct=0.934" ^
  --mts-stop-anchor=signal_low ^
  --wpbr-atr-target=0 ^
  --wpbr-atr-stop=0 ^
  --wpbr-atr-increment=0 ^
  --wpbr-atr-progress=0 ^
  --wpbr-atr-days=0 ^
  "--wpbr-target-pct=1.24" ^
  "--wpbr-stop-pct=0.927" ^
  "--rl-target-pct=1.20" ^
  "--rl-stop-pct=0.934" ^
  --rl-use-sma50 ^
  %PS_ARGS%
exit /b %errorlevel%

