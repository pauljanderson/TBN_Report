@echo off
rem WRL one-knob A/B vs house control (scale 50/50, stop at swing low).
rem Does NOT change run_wrl.bat defaults.
rem
rem Arms (optimizer_systems.WRL_PLAN, one knob at a time):
rem   00_control       scale 50/50, stop_pct=1.0, min-zone off
rem   01_target_range  full exit at range high
rem   02_target_swing  full exit at swing high
rem   03_scale_033     33%% at range high
rem   04_scale_067     67%% at range high
rem   05_stop_098      stop = 98%% of swing low
rem   06_stop_099      stop = 99%% of swing low
rem   07_minzone_01    demand zone must be >= 1%%
rem   08_minzone_02    demand zone must be >= 2%%
rem
rem   run_wrl_ab.bat
rem   run_wrl_ab.bat AAPL,MSFT,NVDA
rem   set WRL_AB_SMOKE=1 & run_wrl_ab.bat
rem
rem Outputs: drive\paul_experiments\wrl\ab_levers\<arm>\
rem Comparison: drive\paul_experiments\wrl\ab_levers\comparison.html
rem             docs\systems\wrl_ab.html
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1
set "EXTRA="
if /i "%WRL_AB_SMOKE%"=="1" set "EXTRA=--smoke"
if not "%~1"=="" (
  "%PY%" "%~dp0tools\run_wrl_ab.py" --symbols "%~1" %EXTRA%
) else (
  "%PY%" "%~dp0tools\run_wrl_ab.py" %EXTRA%
)
exit /b %errorlevel%
