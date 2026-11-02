@echo off
rem Bidirectional venue → kitchen → dashboard sync.
rem Reads latest pm/kalshi recon dumps (or live pulls when available),
rem books missing opens + today fills as claim+sent onto orders.jsonl,
rem then rebuilds orders_performance.html and the dashboard.
rem Does not place, cancel, or sell.

setlocal EnableExtensions
cd /d "%~dp0"

if not defined PY call "%~dp0resolve_python.bat"
if errorlevel 1 (
  python -u -c "import sys; sys.path.insert(0,'tools'); import venue_open_miss_ingest as v; import json; print(json.dumps(v.ingest_from_venue_pulls(persist=True, include_fills=True, rebuild=True), default=str))"
  exit /b %ERRORLEVEL%
)
"%PY%" -u -c "import sys; sys.path.insert(0,'tools'); import venue_open_miss_ingest as v; import json; print(json.dumps(v.ingest_from_venue_pulls(persist=True, include_fills=True, rebuild=True), default=str))"
exit /b %ERRORLEVEL%
