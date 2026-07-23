@echo off
rem Compatibility wrapper: PBR was renamed to WPBR. Prefer run_wpbr.bat.
call "%~dp0run_wpbr.bat" %*
exit /b %errorlevel%
