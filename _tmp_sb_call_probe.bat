@echo off
echo [child] star=%*
set i=0
:loop
if "%~1"=="" goto :done
set /a i+=1
echo [child] arg%i%=[%~1]
shift
goto loop
:done
