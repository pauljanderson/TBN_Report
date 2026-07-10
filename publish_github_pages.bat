@echo off
rem Generate investment report, copy to docs\ for GitHub Pages, optionally push.
rem   publish_github_pages.bat --push        generate + publish + git push (~1-2 min deploy)
rem   publish_github_pages.bat               generate + local docs/ only (live site unchanged)
rem   publish_github_pages.bat --no-generate --push   copy existing Latest only, then push
setlocal EnableExtensions
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1
:py_ok
"%PY%" "%~dp0scripts\publish_github_pages.py" %*
exit /b %errorlevel%
