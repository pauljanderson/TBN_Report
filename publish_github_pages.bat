@echo off
rem Generate all Pages reports (including historical performance), copy to docs\, optionally push.
rem   publish_github_pages.bat --push        generate + copy docs/ + push origin/main (Pages deploys from main only)
rem   publish_github_pages.bat               generate + local docs/ only (live site unchanged)
rem   publish_github_pages.bat --no-generate --push   copy existing Latest only, then push
setlocal EnableExtensions
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1
:py_ok
"%PY%" "%~dp0scripts\publish_github_pages.py" %*
exit /b %errorlevel%
