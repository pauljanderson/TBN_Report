@echo off
setlocal EnableDelayedExpansion
pushd "%~dp0"

REM Merge audit CSVs into drive\all.csv (or all_yh.csv for YH mode).
REM NOTE: This script does NOT modify cell contents. Timestamp_Drive uses =HYPERLINK(...)
REM   for click-through in Excel; Excel may show a leading "'" in the formula bar.
REM
REM Usage:
REM   concat.bat                  merge BRT_Audit_Report_*.csv + IND_Audit_Report_*.csv + MTS_Audit_Report_*.csv -> all.csv
REM   concat.bat yh               merge YH_Audit_Report_*.csv -> all_yh.csv
REM   concat.bat 26062211         merge BRT+IND+YH+MTS *_Audit_Report_26062211*.csv -> all.csv
REM   concat.bat yh 26062211      merge YH_Audit_Report_26062211*.csv -> all_yh.csv
REM
REM If the first file alphabetically has different columns than later files, narrow the filter
REM or move older CSVs out of the folder before merging.

if exist "Drive\" (
  set "MERGE_DIR=%~dp0Drive"
) else if exist "drive\" (
  set "MERGE_DIR=%~dp0drive"
) else (
  echo ERROR: Neither "Drive" nor "drive" folder found next to concat.bat.
  popd
  exit /b 1
)

set "MODE=brt_ind"
set "TS_FILTER="
set "OUT_NAME=all.csv"

if /I "%~1"=="yh" (
  set "MODE=yh"
  set "OUT_NAME=all_yh.csv"
  if not "%~2"=="" set "TS_FILTER=%~2"
) else if not "%~1"=="" (
  set "TS_FILTER=%~1"
)

if "!MODE!"=="yh" (
  if "!TS_FILTER!"=="" (
    set "PAT1=YH_Audit_Report_*.csv"
  ) else (
    set "PAT1=YH_Audit_Report_!TS_FILTER!*.csv"
  )
  set "PAT2="
  set "PAT3="
  set "PAT4="
) else (
  if "!TS_FILTER!"=="" (
    set "PAT1=BRT_Audit_Report_*.csv"
    set "PAT2=IND_Audit_Report_*.csv"
    set "PAT3=MTS_Audit_Report_*.csv"
    set "PAT4="
  ) else (
    set "PAT1=BRT_Audit_Report_!TS_FILTER!*.csv"
    set "PAT2=IND_Audit_Report_!TS_FILTER!*.csv"
    set "PAT3=YH_Audit_Report_!TS_FILTER!*.csv"
    set "PAT4=MTS_Audit_Report_!TS_FILTER!*.csv"
  )
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$d = $env:MERGE_DIR;" ^
  "$patterns = @($env:PAT1);" ^
  "if ($env:PAT2) { $patterns += $env:PAT2 };" ^
  "if ($env:PAT3) { $patterns += $env:PAT3 };" ^
  "if ($env:PAT4) { $patterns += $env:PAT4 };" ^
  "$patterns = @($patterns | Where-Object { $_ });" ^
  "$files = @();" ^
  "foreach ($pat in $patterns) { $files += @(Get-ChildItem -LiteralPath $d -Filter $pat -ErrorAction SilentlyContinue) };" ^
  "$files = @($files | Sort-Object Name -Unique);" ^
  "if ($files.Count -eq 0) { Write-Error ('No files matching ' + ($patterns -join ' or ') + ' in ' + $d); exit 1 };" ^
  "$out = Join-Path $d $env:OUT_NAME;" ^
  "$utf8 = New-Object System.Text.UTF8Encoding $false;" ^
  "$sw = New-Object System.IO.StreamWriter($out, $false, $utf8);" ^
  "try {" ^
  "  $first = $true;" ^
  "  foreach ($f in $files) {" ^
  "    $sr = New-Object System.IO.StreamReader($f.FullName, [System.Text.Encoding]::UTF8);" ^
  "    try {" ^
  "      if (-not $first) { [void]$sr.ReadLine() }" ^
  "      while (($line = $sr.ReadLine()) -ne $null) { $sw.WriteLine($line) }" ^
  "    } finally { $sr.Close() }" ^
  "    $first = $false" ^
  "  }" ^
  "} finally { $sw.Close() };" ^
  "Write-Host ('Wrote ' + $out + '  (' + $files.Count + ' files: ' + ($patterns -join ', ') + ')')"

set ERR=!ERRORLEVEL!
popd
exit /b !ERR!
