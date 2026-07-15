@echo off
rem Build TOS_Zones_Generator.exe (share with others — no Python required to run).
setlocal EnableExtensions
cd /d "%~dp0"

set "PY="
if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY (
  echo ERROR: Python not found. Install Python 3.10+ or set PY to python.exe
  exit /b 1
)

echo Installing PyInstaller if needed...
"%PY%" -m pip install pyinstaller --quiet
if errorlevel 1 (
  echo ERROR: pip install pyinstaller failed
  exit /b 1
)

set "DIST=%~dp0..\drive\tos\release"
if not exist "%DIST%" mkdir "%DIST%"

echo Building TOS_Zones_Generator.exe ...
"%PY%" -m PyInstaller --noconfirm --onefile --name TOS_Zones_Generator --distpath "%DIST%" --workpath "%~dp0build_pyinstaller" --specpath "%~dp0build_pyinstaller" --paths "%~dp0" "%~dp0tos_zones_cli.py"
if errorlevel 1 exit /b 1

copy /Y "%~dp0TOS_Zones_Generator_README.txt" "%DIST%\TOS_Zones_Generator_README.txt" >nul
"%PY%" "%~dp0make_csv_templates.py" >nul

echo.
echo SUCCESS: %DIST%\TOS_Zones_Generator.exe
echo Also copied: README, SYMBOL_template.csv, NFLX_example.csv
echo Share the whole release folder with your brother.
exit /b 0
