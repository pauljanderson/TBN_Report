@echo off
rem Read-only Kalshi dump for Cloud Agent reconcile.
rem Uses secrets\kalshi_private_key.pem + secrets\kalshi_key_id.txt
rem Writes JSON under drive\...\kalshi_recon_dump\ (Google Drive sync)
rem and local\...\kalshi_recon_dump\. Does not place, cancel, or sell.
setlocal
cd /d "%~dp0"

if not exist "secrets\kalshi_private_key.pem" (
  echo MISSING secrets\kalshi_private_key.pem
  echo Put the Kalshi API private key PEM there ^(gitignored^).
  exit /b 2
)
if not exist "secrets\kalshi_key_id.txt" (
  echo MISSING secrets\kalshi_key_id.txt
  echo Put the key id UUID from Kalshi Account Settings on one line.
  exit /b 2
)

set "PY="
if exist "%LocalAppData%\Programs\Python\Python310\python.exe" set "PY=%LocalAppData%\Programs\Python\Python310\python.exe"
if not defined PY if exist "C:\Users\songg\AppData\Local\Programs\Python\Python310\python.exe" set "PY=C:\Users\songg\AppData\Local\Programs\Python\Python310\python.exe"
if not defined PY set "PY=python"

echo Using: %PY%
"%PY%" -u tools\dump_kalshi_recon.py --days 3 %*
set "ERR=%ERRORLEVEL%"
echo.
echo When Drive finishes syncing, reply to the Cloud Agent:
echo   Kalshi recon dump is ready
echo File to confirm:
echo   drive\paul_experiments\prediction_market_arb_exhaustive_20261017\kalshi_recon_dump\kalshi_recon_dump_latest.json
exit /b %ERR%
