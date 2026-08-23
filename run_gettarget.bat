@echo off
rem Live stop/target for active systems. IND is deprecated and excluded from scheduled targets.
rem Systems: RL, BRT, YH, MTS, WPBR, RS, SB (StockBee), CS (CAN SLIM).
rem MVCP retired 2026-08-21 — still mapped in getTarget.py if any historical Open lots remain.
rem Qull/Kell (EMA trail) are not mapped yet — use --list-systems on getTarget.py.
rem Standalone: double-click or call from DailyRun.
setlocal EnableExtensions
cd /d "%~dp0"

if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

if not defined PER_SYMBOL_SETTINGS set "PER_SYMBOL_SETTINGS=stock_analysis\Per_Symbol_Optimized_Settings_Approved_Latest.json"

rem Optional: only pass --per-symbol-settings when the JSON exists (never pass an empty token).
set "PS_ARGS="
if exist "%~dp0%PER_SYMBOL_SETTINGS%" set "PS_ARGS=--per-symbol-settings %PER_SYMBOL_SETTINGS%"

rem IMPORTANT: no blank lines between caret-continued args — cmd injects "\n" as argv and argparse fails with
rem "getTarget.py: error: unrecognized arguments:" (empty / invisible).
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
  --rs-atr-target=0 ^
  --rs-atr-stop=0 ^
  --rs-atr-increment=0 ^
  --rs-atr-progress=0 ^
  --rs-atr-days=0 ^
  "--rs-target-pct=1.25" ^
  "--rs-stop-pct=0.88" ^
  --sb-atr-target=0 ^
  --sb-atr-stop=0 ^
  --sb-atr-increment=0 ^
  --sb-atr-progress=0 ^
  --sb-atr-days=0 ^
  "--sb-target-pct=1.097" ^
  "--sb-stop-pct=1.0" ^
  --sb-stop-anchor=signal_low ^
  "--sb-fallback-stop-pct=0.922" ^
  --mvcp-atr-target=0 ^
  --mvcp-atr-stop=0 ^
  --mvcp-atr-increment=0 ^
  --mvcp-atr-progress=0 ^
  --mvcp-atr-days=0 ^
  "--mvcp-target-pct=1.25" ^
  "--mvcp-stop-pct=0.92" ^
  --cs-atr-target=0 ^
  --cs-atr-stop=0 ^
  --cs-atr-increment=0 ^
  --cs-atr-progress=0 ^
  --cs-atr-days=0 ^
  "--cs-target-pct=1.20" ^
  "--cs-stop-pct=0.92" ^
  "--rl-target-pct=1.20" ^
  "--rl-stop-pct=0.934" ^
  --rl-use-sma50 %PS_ARGS% %*

exit /b %errorlevel%
