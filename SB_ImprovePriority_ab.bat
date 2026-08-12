@echo off
rem Alias → run_sb_hint_ab.bat (SB ImprovePriority / ImproveHints A/B)
setlocal EnableExtensions
cd /d "%~dp0"
call "%~dp0run_sb_hint_ab.bat" %*
exit /b %ERRORLEVEL%
