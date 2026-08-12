@echo off
rem Poll drive\mobile_inbox\commands_pending.txt and run whitelist-only actions.
rem Safe for Task Scheduler / manual run while away (phone edits Drive files).
rem Whitelist: ingest_trades | apply_gettarget_patch | run_gettarget | regen_reports | publish_pages_push | run_vz
setlocal EnableExtensions
cd /d "%~dp0"
if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 exit /b 1
"%PY%" "%~dp0tools\run_mobile_inbox.py" %*
exit /b %errorlevel%
