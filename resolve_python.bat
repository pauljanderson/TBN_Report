@echo off
rem Set PY to a working python.exe if not already set (same order as DailyRun.bat).
if defined PY if exist "%PY%" exit /b 0
set "PY="
if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not defined PY for /f "tokens=2*" %%a in ('reg query "HKCU\Software\Python\PythonCore\3.10\InstallPath" /v ExecutablePath 2^>nul ^| find "ExecutablePath"') do set "PY=%%b"
if not defined PY set "PY=C:\Program Files\WindowsApps\PythonSoftwareFoundation.Python.3.10_3.10.3056.0_x64__qbz5n2kfra8p0\python3.10.exe"
if not exist "%PY%" if exist "C:\Program Files\WindowsApps\PythonSoftwareFoundation.Python.3.10_3.10.3056.0_x64__qbz5n2kfra8p0\python.exe" set "PY=C:\Program Files\WindowsApps\PythonSoftwareFoundation.Python.3.10_3.10.3056.0_x64__qbz5n2kfra8p0\python.exe"
if not defined PY for /f "delims=" %%P in ('where python 2^>nul') do set "PY=%%P" & goto :found
:found
if not defined PY (
  echo ERROR: Python not found. Run DailyRun.bat once, or set PY to your python.exe.>&2
  echo        Example: set PY=%%LOCALAPPDATA%%\Programs\Python\Python310\python.exe>&2
  exit /b 1
)
if not exist "%PY%" (
  echo ERROR: Python not found at %PY%>&2
  exit /b 1
)
exit /b 0
