@echo off
REM RL entry-MTM exit AB vs Paul 40d@29% control (tradable 764)
cd /d "%~dp0.."
python tools\rl_entry_exit_ab.py --skip-existing --jobs 2 --workers 12 %*
