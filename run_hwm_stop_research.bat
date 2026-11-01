@echo off
rem Research only. DailyRun.bat does not call this file.
rem Sets HWM_* env, then calls the normal system bat with no extra arguments.
rem The engine default stays today's live book when these variables are absent.
rem HWM_RESEARCH_OUT keeps the CSVs out of drive\*_LatestRun_*.
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1

rem MTS copy-latest refreshes drive\MTS_LatestRun_*. Do not do that here.
set "DAILYRUN_WAVE=1"

set "STAMP=%~dp0drive\paul_experiments\hwm_stop_rerun_signals_20261015\runs"
if not exist "%STAMP%" mkdir "%STAMP%"

set "WHICH=%~1"
if "%WHICH%"=="" set "WHICH=ALL"

if /i "%WHICH%"=="ALL" goto :all
if /i "%WHICH%"=="BRT" goto :brt
if /i "%WHICH%"=="RL" goto :rl
if /i "%WHICH%"=="YH" goto :yh
if /i "%WHICH%"=="MTS" goto :mts
if /i "%WHICH%"=="WPBR" goto :wpbr
if /i "%WHICH%"=="RS" goto :rs
if /i "%WHICH%"=="RSI" goto :rsi
echo Usage: run_hwm_stop_research.bat [ALL^|BRT^|RL^|YH^|MTS^|WPBR^|RS^|RSI]
exit /b 1

:all
call "%~f0" BRT & call "%~f0" RL & call "%~f0" YH & call "%~f0" MTS & call "%~f0" WPBR & call "%~f0" RS & call "%~f0" RSI
exit /b 0

:clear
set "HWM_ACT_PCT="
set "HWM_KEEP="
set "HWM_STOP_PCT="
set "HWM_RL_STOP_PCT="
set "HWM_RL_SCALE_LADDER="
set "HWM_RL_ENTRY_TARGET_PCT="
set "HWM_RESEARCH_OUT="
exit /b 0

:brt
call :clear
set "HWM_ACT_PCT=6"
set "HWM_KEEP=0.70"
set "HWM_STOP_PCT=0.864"
set "HWM_RESEARCH_OUT=%STAMP%\BRT"
if not defined BRT_WORKERS set "BRT_WORKERS=6"
echo [HWM research] Break and ReTest base 13.6%% under trigger low, trail 6%% keep 70%%
call "%~dp0run_brt.bat"
exit /b %errorlevel%

:rl
call :clear
set "HWM_ACT_PCT=6"
set "HWM_KEEP=0.80"
set "HWM_RL_STOP_PCT=0.9935"
set "HWM_RL_SCALE_LADDER=off"
set "HWM_RL_ENTRY_TARGET_PCT=0"
set "HWM_RESEARCH_OUT=%STAMP%\RL"
if not defined RL_WORKERS set "RL_WORKERS=4"
echo [HWM research] Rocket Launcher base 0.65%% under signal low, trail 6%% keep 80%%, ladder off
call "%~dp0run_rl.bat"
exit /b %errorlevel%

:yh
call :clear
set "HWM_ACT_PCT=2"
set "HWM_KEEP=0.70"
set "HWM_STOP_PCT=0.9905"
set "HWM_RESEARCH_OUT=%STAMP%\YH"
if not defined YH_WORKERS set "YH_WORKERS=6"
echo [HWM research] Year High base 0.95%% under trigger low, trail 2%% keep 70%%
call "%~dp0run_yh.bat"
exit /b %errorlevel%

:mts
call :clear
set "HWM_ACT_PCT=4"
set "HWM_KEEP=0.60"
set "HWM_STOP_PCT=0.9744"
set "HWM_RESEARCH_OUT=%STAMP%\MTS"
if not defined MTS_WORKERS set "MTS_WORKERS=6"
echo [HWM research] Magic Touch base 2.56%% under trigger low, trail 4%% keep 60%%
call "%~dp0run_mts.bat"
exit /b %errorlevel%

:wpbr
call :clear
set "HWM_ACT_PCT=2"
set "HWM_KEEP=0.80"
set "HWM_STOP_PCT=0.9697"
set "HWM_RESEARCH_OUT=%STAMP%\WPBR"
if not defined WPBR_WORKERS set "WPBR_WORKERS=4"
echo [HWM research] Weekly Pivot Break and Retest base 3.03%% under trigger low, trail 2%% keep 80%%
call "%~dp0run_wpbr.bat"
exit /b %errorlevel%

:rs
call :clear
set "HWM_ACT_PCT=10"
set "HWM_KEEP=0.80"
set "HWM_RESEARCH_OUT=%STAMP%\RS"
if not defined RS_WORKERS set "RS_WORKERS=4"
echo [HWM research] Relative Strength vs SPY live base entry x 0.85, trail 10%% keep 80%%
call "%~dp0run_rs.bat"
exit /b %errorlevel%

:rsi
call :clear
set "HWM_ACT_PCT=6"
set "HWM_KEEP=0.80"
set "HWM_RESEARCH_OUT=%STAMP%\RSI"
if not defined RSI_WORKERS set "RSI_WORKERS=4"
echo [HWM research] Relative Strength Index no new price base, trail 6%% keep 80%%
call "%~dp0run_rsi.bat"
exit /b %errorlevel%
