@echo off
rem Open a Cursor/VS Code multi-root workspace for the three repos.
setlocal EnableExtensions
cd /d "%~dp0"

set "WS=%~dp0TBN_Predictions_Spotify.code-workspace"
if exist "%WS%" (
  where cursor >nul 2>&1
  if not errorlevel 1 (
    start "" cursor "%WS%"
    goto :done
  )
  where code >nul 2>&1
  if not errorlevel 1 (
    start "" code "%WS%"
    goto :done
  )
  echo Open this file manually in Cursor: %WS%
) else (
  echo Workspace file missing: %WS%
)
:done
if not defined REPO_SPLIT_NOPAUSE pause
exit /b 0
