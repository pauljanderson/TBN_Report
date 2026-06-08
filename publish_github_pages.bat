@echo off
rem Copy Latest reports to docs\ for GitHub Pages. Add --push after git remote is configured.
setlocal EnableExtensions
cd /d "%~dp0"
if not defined PY (
  for /f "delims=" %%P in ('where python 2^>nul') do set "PY=%%P" & goto :py_ok
  echo ERROR: set PY to your python.exe or add python to PATH.>&2
  exit /b 1
)
:py_ok
"%PY%" "%~dp0scripts\publish_github_pages.py" %*
exit /b %errorlevel%
