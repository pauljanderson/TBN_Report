@echo off
rem Python Rocket Launcher (rl_mode=true) — outputs RL_Closed|Open|... in drive\
rem Standalone: double-click or call from DailyRun. Override: set RL_SYMBOLS=SYM1,SYM2 before calling.
rem IND_TC_*: not on RL_Closed yet (separate writer; indicators only for mandatory/exclude gates).
setlocal EnableExtensions
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

if not defined RL_SYMBOLS set "RL_SYMBOLS=MTZ,NXT,APP,SAIA,NFLX,HUBS,FIVN,AGX,HCI,GHM,MU,AMAT,WRLD,RNG,CF,STX,GLW,LMAT,LMND,DXPE,LMB,EXEL,NGVC,AU,AGI,AA,TGB,PDEX,GFI,UTI,NTRA,STLD,TORXF,DOCN,FN,VLO,INOD,AMD,TTMI,SPRY,BBW,CRWD,TPC,AX,AEHR,ANIP,PSIX,AEM,KINS,MOD,EDVMF,WDC,TGLS,CMCL,CORT,NVAX,AMKR,PATK,ABUS"
if not defined PER_SYMBOL_SETTINGS set "PER_SYMBOL_SETTINGS=stock_analysis\Per_Symbol_Optimized_Settings_Approved_Latest.json"

set "PS_ARGS="
if exist "%~dp0%PER_SYMBOL_SETTINGS%" set "PS_ARGS=--per-symbol-settings %PER_SYMBOL_SETTINGS%"

rem Production default: rl_too_high off (0); rl_dip_pct=1.041 (±4.1%). Per-symbol JSON also stores 0 for RL symbols.
rem Cheap analysis (ONE_LINER / FIT / ImproveHints) emits automatically after the run.
rem Charts + CRWD-style HTML (NOT in DailyRun): python stock_analysis\rl_post_run_analysis.py --stamp <ts> --charts
"%PY%" stock_analysis\rocket_tbn.py data\newdata\data -o drive -w 5 --aggressive --no-regression -v rl_mode=true -v brt_zones=false -v yh_zones=false -v indicator_buy=off -v rl_sma_qual=1 -v ATR_LOW=off -v ATR_HIGH=off -v rl_slope_threshold=0 -v rl_too_high=0 -v rl_dip_pct=1.041 %PS_ARGS% -s "%RL_SYMBOLS%"
exit /b %errorlevel%

