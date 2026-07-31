@echo off
rem Rerun unique RL A/B configs discovered from 260730* stamps.
rem Base = run_rl.bat fair production settings; RL60 universe.
rem post_target flags for 111*/121*/124* were INFERRED (not in RL_Report).
rem See rl_ab_stamp_flags_260730.csv / .txt for stamp → flags map.
setlocal EnableExtensions
cd /d "%~dp0..\.."
if not defined PY call "%~dp0..\..\resolve_python.bat"
if errorlevel 1 exit /b 1

set "RL_SYMBOLS=MTZ,NXT,APP,SAIA,NFLX,HUBS,FIVN,AGX,HCI,GHM,MU,AMAT,WRLD,RNG,CF,STX,GLW,LMAT,LMND,DXPE,LMB,EXEL,NGVC,AU,AGI,AA,TGB,PDEX,GFI,UTI,NTRA,STLD,TORXF,DOCN,FN,VLO,INOD,AMD,TTMI,SPRY,BBW,CRWD,TPC,AX,AEHR,ANIP,PSIX,AEM,KINS,MOD,EDVMF,WDC,TGLS,CMCL,CORT,NVAX,AMKR,PATK,ABUS"
if not defined PER_SYMBOL_SETTINGS set "PER_SYMBOL_SETTINGS=stock_analysis\Per_Symbol_Optimized_Settings_Approved_Latest.json"
set "PS_ARGS="
if exist "%~dp0..\..\%PER_SYMBOL_SETTINGS%" set "PS_ARGS=--per-symbol-settings %PER_SYMBOL_SETTINGS%"

rem Common production base (mirrors run_rl.bat)
set "BASE_V=-v rl_mode=true -v brt_zones=false -v yh_zones=false -v indicator_buy=off -v rl_sma_qual=1 -v ATR_LOW=off -v ATR_HIGH=off -v rl_too_high=0 -v rl_dip_pct=1.041"
set "BASE_CMD=%PY% stock_analysis\rocket_tbn.py data\newdata\data -o drive -w 5 --no-regression"

echo === RL A/B grid: 69 unique configs ===
echo Flag map: drive\paul_experiments\rl_ab_stamp_flags_260730.csv

echo.
echo ========== [1/69] 01_FAIR_OFF_BASELINE ==========
echo Exemplar stamp: 260730094107  (also: 260730094107,260730095542,260730100938,260730104408)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.163 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on 01_FAIR_OFF_BASELINE & exit /b %ERRORLEVEL%
echo.
echo ========== [2/69] cut_0.05 ==========
echo Exemplar stamp: 260730095556  (also: 260730095556)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.05 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.163 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on cut_0.05 & exit /b %ERRORLEVEL%
echo.
echo ========== [3/69] cut_0.1 ==========
echo Exemplar stamp: 260730095553  (also: 260730095553)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.1 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.163 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on cut_0.1 & exit /b %ERRORLEVEL%
echo.
echo ========== [4/69] cut_0.15 ==========
echo Exemplar stamp: 260730095549  (also: 260730095549)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.15 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.163 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on cut_0.15 & exit /b %ERRORLEVEL%
echo.
echo ========== [5/69] cut_0.2 ==========
echo Exemplar stamp: 260730095546  (also: 260730095546)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.2 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.163 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on cut_0.2 & exit /b %ERRORLEVEL%
echo.
echo ========== [6/69] cut_0.21 ==========
echo Exemplar stamp: 260730100025  (also: 260730100025)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.21 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.163 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on cut_0.21 & exit /b %ERRORLEVEL%
echo.
echo ========== [7/69] cut_0.22 ==========
echo Exemplar stamp: 260730100022  (also: 260730100022)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.22 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.163 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on cut_0.22 & exit /b %ERRORLEVEL%
echo.
echo ========== [8/69] cut_0.23 ==========
echo Exemplar stamp: 260730100018  (also: 260730100018)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.23 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.163 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on cut_0.23 & exit /b %ERRORLEVEL%
echo.
echo ========== [9/69] cut_0.24 ==========
echo Exemplar stamp: 260730100015  (also: 260730100015)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.24 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.163 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on cut_0.24 & exit /b %ERRORLEVEL%
echo.
echo ========== [10/69] cut_0.26 ==========
echo Exemplar stamp: 260730100011  (also: 260730100011)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.26 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.163 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on cut_0.26 & exit /b %ERRORLEVEL%
echo.
echo ========== [11/69] cut_0.27 ==========
echo Exemplar stamp: 260730100007  (also: 260730100007)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.27 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.163 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on cut_0.27 & exit /b %ERRORLEVEL%
echo.
echo ========== [12/69] cut_0.28 ==========
echo Exemplar stamp: 260730100004  (also: 260730100004)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.28 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.163 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on cut_0.28 & exit /b %ERRORLEVEL%
echo.
echo ========== [13/69] cut_0.29 ==========
echo Exemplar stamp: 260730100001  (also: 260730100001)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.29 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.163 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on cut_0.29 & exit /b %ERRORLEVEL%
echo.
echo ========== [14/69] cut_0.3 ==========
echo Exemplar stamp: 260730095538  (also: 260730095538)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.3 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.163 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on cut_0.3 & exit /b %ERRORLEVEL%
echo.
echo ========== [15/69] slope_0.05 ==========
echo Exemplar stamp: 260730100942  (also: 260730100942)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.05 -v rl_slope_period=30 -v rl_expansion=1.163 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on slope_0.05 & exit /b %ERRORLEVEL%
echo.
echo ========== [16/69] slope_0.0643 ==========
echo Exemplar stamp: 260730100945  (also: 260730100945)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0643 -v rl_slope_period=30 -v rl_expansion=1.163 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on slope_0.0643 & exit /b %ERRORLEVEL%
echo.
echo ========== [17/69] slope_0.08 ==========
echo Exemplar stamp: 260730100948  (also: 260730100948)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.08 -v rl_slope_period=30 -v rl_expansion=1.163 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on slope_0.08 & exit /b %ERRORLEVEL%
echo.
echo ========== [18/69] slope_0.1 ==========
echo Exemplar stamp: 260730100952  (also: 260730100952)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.1 -v rl_slope_period=30 -v rl_expansion=1.163 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on slope_0.1 & exit /b %ERRORLEVEL%
echo.
echo ========== [19/69] slope_0.11 ==========
echo Exemplar stamp: 260730101207  (also: 260730101207)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.11 -v rl_slope_period=30 -v rl_expansion=1.163 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on slope_0.11 & exit /b %ERRORLEVEL%
echo.
echo ========== [20/69] slope_0.12 ==========
echo Exemplar stamp: 260730101211  (also: 260730101211)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.12 -v rl_slope_period=30 -v rl_expansion=1.163 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on slope_0.12 & exit /b %ERRORLEVEL%
echo.
echo ========== [21/69] slope_0.13 ==========
echo Exemplar stamp: 260730101214  (also: 260730101214)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.13 -v rl_slope_period=30 -v rl_expansion=1.163 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on slope_0.13 & exit /b %ERRORLEVEL%
echo.
echo ========== [22/69] slope_0.14 ==========
echo Exemplar stamp: 260730101217  (also: 260730101217)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.14 -v rl_slope_period=30 -v rl_expansion=1.163 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on slope_0.14 & exit /b %ERRORLEVEL%
echo.
echo ========== [23/69] slope_0.15 ==========
echo Exemplar stamp: 260730101221  (also: 260730101221)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.15 -v rl_slope_period=30 -v rl_expansion=1.163 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on slope_0.15 & exit /b %ERRORLEVEL%
echo.
echo ========== [24/69] exp_1.11 ==========
echo Exemplar stamp: 260730104009  (also: 260730104009)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.11 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on exp_1.11 & exit /b %ERRORLEVEL%
echo.
echo ========== [25/69] exp_1.12 ==========
echo Exemplar stamp: 260730104013  (also: 260730104013)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.12 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on exp_1.12 & exit /b %ERRORLEVEL%
echo.
echo ========== [26/69] exp_1.13 ==========
echo Exemplar stamp: 260730104017  (also: 260730104017)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.13 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on exp_1.13 & exit /b %ERRORLEVEL%
echo.
echo ========== [27/69] exp_1.14 ==========
echo Exemplar stamp: 260730104021  (also: 260730104021)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.14 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on exp_1.14 & exit /b %ERRORLEVEL%
echo.
echo ========== [28/69] exp_1.15 ==========
echo Exemplar stamp: 260730104024  (also: 260730104024)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.15 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on exp_1.15 & exit /b %ERRORLEVEL%
echo.
echo ========== [29/69] exp_1.16 ==========
echo Exemplar stamp: 260730104028  (also: 260730104028)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.16 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on exp_1.16 & exit /b %ERRORLEVEL%
echo.
echo ========== [30/69] exp_1.161 ==========
echo Exemplar stamp: 260730104401  (also: 260730104401)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.161 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on exp_1.161 & exit /b %ERRORLEVEL%
echo.
echo ========== [31/69] exp_1.162 ==========
echo Exemplar stamp: 260730104404  (also: 260730104404)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.162 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on exp_1.162 & exit /b %ERRORLEVEL%
echo.
echo ========== [32/69] exp_1.164 ==========
echo Exemplar stamp: 260730104411  (also: 260730104411)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.164 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on exp_1.164 & exit /b %ERRORLEVEL%
echo.
echo ========== [33/69] exp_1.165 ==========
echo Exemplar stamp: 260730104415  (also: 260730104415)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.165 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on exp_1.165 & exit /b %ERRORLEVEL%
echo.
echo ========== [34/69] exp_1.166 ==========
echo Exemplar stamp: 260730104418  (also: 260730104418)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.166 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on exp_1.166 & exit /b %ERRORLEVEL%
echo.
echo ========== [35/69] exp_1.167 ==========
echo Exemplar stamp: 260730104421  (also: 260730104421)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.167 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on exp_1.167 & exit /b %ERRORLEVEL%
echo.
echo ========== [36/69] exp_1.168 ==========
echo Exemplar stamp: 260730104425  (also: 260730104425)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.168 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on exp_1.168 & exit /b %ERRORLEVEL%
echo.
echo ========== [37/69] exp_1.169 ==========
echo Exemplar stamp: 260730104428  (also: 260730104428)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.169 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on exp_1.169 & exit /b %ERRORLEVEL%
echo.
echo ========== [38/69] exp_1.17 ==========
echo Exemplar stamp: 260730104031  (also: 260730104031)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.17 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on exp_1.17 & exit /b %ERRORLEVEL%
echo.
echo ========== [39/69] exp_1.171 ==========
echo Exemplar stamp: 260730104431  (also: 260730104431)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.171 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on exp_1.171 & exit /b %ERRORLEVEL%
echo.
echo ========== [40/69] exp_1.172 ==========
echo Exemplar stamp: 260730104435  (also: 260730104435)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.172 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on exp_1.172 & exit /b %ERRORLEVEL%
echo.
echo ========== [41/69] exp_1.173 ==========
echo Exemplar stamp: 260730104438  (also: 260730104438)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.173 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on exp_1.173 & exit /b %ERRORLEVEL%
echo.
echo ========== [42/69] exp_1.174 ==========
echo Exemplar stamp: 260730104442  (also: 260730104442)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.174 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on exp_1.174 & exit /b %ERRORLEVEL%
echo.
echo ========== [43/69] exp_1.175 ==========
echo Exemplar stamp: 260730104445  (also: 260730104445)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.175 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on exp_1.175 & exit /b %ERRORLEVEL%
echo.
echo ========== [44/69] exp_1.176 ==========
echo Exemplar stamp: 260730104448  (also: 260730104448)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.176 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on exp_1.176 & exit /b %ERRORLEVEL%
echo.
echo ========== [45/69] exp_1.177 ==========
echo Exemplar stamp: 260730104452  (also: 260730104452)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.177 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on exp_1.177 & exit /b %ERRORLEVEL%
echo.
echo ========== [46/69] exp_1.178 ==========
echo Exemplar stamp: 260730104455  (also: 260730104455)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.178 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on exp_1.178 & exit /b %ERRORLEVEL%
echo.
echo ========== [47/69] exp_1.179 ==========
echo Exemplar stamp: 260730104459  (also: 260730104459)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.179 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on exp_1.179 & exit /b %ERRORLEVEL%
echo.
echo ========== [48/69] exp_1.18 ==========
echo Exemplar stamp: 260730104035  (also: 260730104035)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.18 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on exp_1.18 & exit /b %ERRORLEVEL%
echo.
echo ========== [49/69] exp_1.19 ==========
echo Exemplar stamp: 260730104038  (also: 260730104038)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.19 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on exp_1.19 & exit /b %ERRORLEVEL%
echo.
echo ========== [50/69] pt_stop_bars5_pct0.95 ==========
echo Exemplar stamp: 260730111341  (also: 260730111341)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.163 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=5 -v rl_post_target_reentry_mode=stop_loss -v rl_post_target_stop_pct=0.95 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on pt_stop_bars5_pct0.95 & exit /b %ERRORLEVEL%
echo.
echo ========== [51/69] pt_stop_bars5_pct0.96 ==========
echo Exemplar stamp: 260730111345  (also: 260730111345)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.163 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=5 -v rl_post_target_reentry_mode=stop_loss -v rl_post_target_stop_pct=0.96 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on pt_stop_bars5_pct0.96 & exit /b %ERRORLEVEL%
echo.
echo ========== [52/69] pt_stop_bars5_pct0.97 ==========
echo Exemplar stamp: 260730111348  (also: 260730111348)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.163 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=5 -v rl_post_target_reentry_mode=stop_loss -v rl_post_target_stop_pct=0.97 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on pt_stop_bars5_pct0.97 & exit /b %ERRORLEVEL%
echo.
echo ========== [53/69] pt_stop_bars10_pct0.95 ==========
echo Exemplar stamp: 260730111351  (also: 260730111351)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.163 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=10 -v rl_post_target_reentry_mode=stop_loss -v rl_post_target_stop_pct=0.95 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on pt_stop_bars10_pct0.95 & exit /b %ERRORLEVEL%
echo.
echo ========== [54/69] pt_stop_bars10_pct0.96 ==========
echo Exemplar stamp: 260730111355  (also: 260730111355)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.163 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=10 -v rl_post_target_reentry_mode=stop_loss -v rl_post_target_stop_pct=0.96 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on pt_stop_bars10_pct0.96 & exit /b %ERRORLEVEL%
echo.
echo ========== [55/69] pt_stop_bars10_pct0.97 ==========
echo Exemplar stamp: 260730111358  (also: 260730111358)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.163 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=10 -v rl_post_target_reentry_mode=stop_loss -v rl_post_target_stop_pct=0.97 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on pt_stop_bars10_pct0.97 & exit /b %ERRORLEVEL%
echo.
echo ========== [56/69] pt_stop_bars15_pct0.95 ==========
echo Exemplar stamp: 260730111402  (also: 260730111402)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.163 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=15 -v rl_post_target_reentry_mode=stop_loss -v rl_post_target_stop_pct=0.95 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on pt_stop_bars15_pct0.95 & exit /b %ERRORLEVEL%
echo.
echo ========== [57/69] pt_stop_bars15_pct0.96 ==========
echo Exemplar stamp: 260730111405  (also: 260730111405)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.163 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=15 -v rl_post_target_reentry_mode=stop_loss -v rl_post_target_stop_pct=0.96 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on pt_stop_bars15_pct0.96 & exit /b %ERRORLEVEL%
echo.
echo ========== [58/69] pt_stop_bars15_pct0.97 ==========
echo Exemplar stamp: 260730111408  (also: 260730111408)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.163 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=15 -v rl_post_target_reentry_mode=stop_loss -v rl_post_target_stop_pct=0.97 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on pt_stop_bars15_pct0.97 & exit /b %ERRORLEVEL%
echo.
echo ========== [59/69] pt_minstack_bars10_ms0.03 ==========
echo Exemplar stamp: 260730121415  (also: 260730121415)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.163 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=10 -v rl_post_target_reentry_mode=min_stack -v rl_post_target_min_stack=0.03 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on pt_minstack_bars10_ms0.03 & exit /b %ERRORLEVEL%
echo.
echo ========== [60/69] pt_minstack_bars10_ms0.04 ==========
echo Exemplar stamp: 260730121418  (also: 260730121418)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.163 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=10 -v rl_post_target_reentry_mode=min_stack -v rl_post_target_min_stack=0.04 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on pt_minstack_bars10_ms0.04 & exit /b %ERRORLEVEL%
echo.
echo ========== [61/69] pt_minstack_bars10_ms0.05 ==========
echo Exemplar stamp: 260730121422  (also: 260730121422)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.163 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=10 -v rl_post_target_reentry_mode=min_stack -v rl_post_target_min_stack=0.05 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on pt_minstack_bars10_ms0.05 & exit /b %ERRORLEVEL%
echo.
echo ========== [62/69] pt_minstack_bars10_ms0.06 ==========
echo Exemplar stamp: 260730121425  (also: 260730121425)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.163 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=10 -v rl_post_target_reentry_mode=min_stack -v rl_post_target_min_stack=0.06 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on pt_minstack_bars10_ms0.06 & exit /b %ERRORLEVEL%
echo.
echo ========== [63/69] pt_minstack_bars10_ms0.07 ==========
echo Exemplar stamp: 260730121429  (also: 260730121429)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.163 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=10 -v rl_post_target_reentry_mode=min_stack -v rl_post_target_min_stack=0.07 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on pt_minstack_bars10_ms0.07 & exit /b %ERRORLEVEL%
echo.
echo ========== [64/69] pt_undersma_bars10_u0.01 ==========
echo Exemplar stamp: 260730124615  (also: 260730124615)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.163 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=10 -v rl_post_target_reentry_mode=under_sma_limit -v rl_post_target_under_sma20=0.01 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on pt_undersma_bars10_u0.01 & exit /b %ERRORLEVEL%
echo.
echo ========== [65/69] pt_undersma_bars10_u0.02 ==========
echo Exemplar stamp: 260730124619  (also: 260730124619)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.163 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=10 -v rl_post_target_reentry_mode=under_sma_limit -v rl_post_target_under_sma20=0.02 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on pt_undersma_bars10_u0.02 & exit /b %ERRORLEVEL%
echo.
echo ========== [66/69] pt_undersma_bars10_u0.03 ==========
echo Exemplar stamp: 260730124622  (also: 260730124622)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.163 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=10 -v rl_post_target_reentry_mode=under_sma_limit -v rl_post_target_under_sma20=0.03 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on pt_undersma_bars10_u0.03 & exit /b %ERRORLEVEL%
echo.
echo ========== [67/69] pt_undersma_bars10_u0.04 ==========
echo Exemplar stamp: 260730124625  (also: 260730124625)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.163 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=10 -v rl_post_target_reentry_mode=under_sma_limit -v rl_post_target_under_sma20=0.04 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on pt_undersma_bars10_u0.04 & exit /b %ERRORLEVEL%
echo.
echo ========== [68/69] pt_undersma_bars10_u0.05 ==========
echo Exemplar stamp: 260730124629  (also: 260730124629)
%BASE_CMD% --aggressive %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.163 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=10 -v rl_post_target_reentry_mode=under_sma_limit -v rl_post_target_under_sma20=0.05 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on pt_undersma_bars10_u0.05 & exit /b %ERRORLEVEL%
echo.
echo ========== [69/69] baseline_aggressive_OFF ==========
echo Exemplar stamp: 260730120506  (also: 260730120506)
%BASE_CMD% %BASE_V% -v rl_cut_the_losers=0.25 -v rl_slope_threshold=0.0 -v rl_slope_period=30 -v rl_expansion=1.163 -v rl_stop_pct=0.934 -v rl_target_pct=1.2 -v rl_post_target_reentry_bars=0 %PS_ARGS% -s "%RL_SYMBOLS%"
if errorlevel 1 echo FAILED %ERRORLEVEL% on baseline_aggressive_OFF & exit /b %ERRORLEVEL%

echo.
echo === All unique A/B configs finished ===
exit /b 0
