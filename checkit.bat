@echo off
cd stock_analysis

:: Display the diff first for review
echo Reviewing changes in rocket_brt.py...
git diff rocket_brt.py
echo.

:: Prompt the user for a commit message
set /p commit_message="Enter your commit message: "

:: Execute the git commands using the variable
git add rocket_brt.py
git commit -m "%commit_message%"

cd ..
echo Done!