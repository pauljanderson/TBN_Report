@echo off
setlocal EnableDelayedExpansion
pushd "%~dp0"

REM Merge audit CSVs into drive\all.csv (or all_yh / all_vec / all_wpbr / all_rs / all_rl for mode filters).
REM NOTE: This script does NOT modify cell contents. Timestamp_Drive uses =HYPERLINK(...)
REM   for click-through in Excel; Excel may show a leading "'" in the formula bar.
REM
REM Usage:
REM   concat.bat                  merge BRT+IND+MTS Audit_Report_*.csv -> all.csv
REM   concat.bat yh               merge YH_Audit_Report_*.csv -> all_yh.csv
REM   concat.bat vec              merge VEC_Audit_Report_*.csv -> all_vec.csv
REM   concat.bat wpbr             merge WPBR_Audit_Report_*.csv -> all_wpbr.csv
REM   concat.bat pbr              legacy alias for wpbr (also matches old PBR_Audit_Report_*)
REM   concat.bat rs               merge RS_Audit_Report_*.csv -> all_rs.csv
REM   concat.bat rl               merge RL_Audit_Report_*.csv -> all_rl.csv
REM   concat.bat 26062211         merge BRT+IND+YH+VEC+WPBR+PBR+MTS+RS+RL *_Audit_Report_26062211*.csv -> all.csv
REM   concat.bat yh 26062211      merge YH_Audit_Report_26062211*.csv -> all_yh.csv
REM   concat.bat vec 26062211     merge VEC_Audit_Report_26062211*.csv -> all_vec.csv
REM   concat.bat wpbr 26062211    merge WPBR_Audit_Report_26062211*.csv -> all_wpbr.csv
REM   concat.bat rs 26062211      merge RS_Audit_Report_26062211*.csv -> all_rs.csv
REM   concat.bat rl 26062211      merge RL_Audit_Report_26062211*.csv -> all_rl.csv
REM
REM If the first file alphabetically has different columns than later files, narrow the filter
REM or move older CSVs out of the folder before merging.

REM Prefer lowercase "drive" so MERGE_DIR matches on-disk folder name (Windows is case-insensitive).
if exist "drive\" (
  set "MERGE_DIR=%~dp0drive"
) else if exist "Drive\" (
  set "MERGE_DIR=%~dp0Drive"
) else (
  echo ERROR: Neither "Drive" nor "drive" folder found next to concat.bat.
  popd
  exit /b 1
)

set "MODE=brt_ind"
set "TS_FILTER="
set "OUT_NAME=all.csv"
set "PATS="

if /I "%~1"=="yh" (
  set "MODE=yh"
  set "OUT_NAME=all_yh.csv"
  if not "%~2"=="" set "TS_FILTER=%~2"
) else if /I "%~1"=="vec" (
  set "MODE=vec"
  set "OUT_NAME=all_vec.csv"
  if not "%~2"=="" set "TS_FILTER=%~2"
) else if /I "%~1"=="wpbr" (
  set "MODE=wpbr"
  set "OUT_NAME=all_wpbr.csv"
  if not "%~2"=="" set "TS_FILTER=%~2"
) else if /I "%~1"=="pbr" (
  rem Legacy alias for wpbr
  set "MODE=wpbr"
  set "OUT_NAME=all_wpbr.csv"
  if not "%~2"=="" set "TS_FILTER=%~2"
) else if /I "%~1"=="rs" (
  set "MODE=rs"
  set "OUT_NAME=all_rs.csv"
  if not "%~2"=="" set "TS_FILTER=%~2"
) else if /I "%~1"=="rl" (
  set "MODE=rl"
  set "OUT_NAME=all_rl.csv"
  if not "%~2"=="" set "TS_FILTER=%~2"
) else if not "%~1"=="" (
  set "TS_FILTER=%~1"
)

if "!MODE!"=="yh" (
  if "!TS_FILTER!"=="" (
    set "PATS=YH_Audit_Report_*.csv"
  ) else (
    set "PATS=YH_Audit_Report_!TS_FILTER!*.csv"
  )
) else if "!MODE!"=="vec" (
  if "!TS_FILTER!"=="" (
    set "PATS=VEC_Audit_Report_*.csv"
  ) else (
    set "PATS=VEC_Audit_Report_!TS_FILTER!*.csv"
  )
) else if "!MODE!"=="wpbr" (
  if "!TS_FILTER!"=="" (
    set "PATS=WPBR_Audit_Report_*.csv;PBR_Audit_Report_*.csv"
  ) else (
    set "PATS=WPBR_Audit_Report_!TS_FILTER!*.csv;PBR_Audit_Report_!TS_FILTER!*.csv"
  )
) else if "!MODE!"=="rs" (
  if "!TS_FILTER!"=="" (
    set "PATS=RS_Audit_Report_*.csv"
  ) else (
    set "PATS=RS_Audit_Report_!TS_FILTER!*.csv"
  )
) else if "!MODE!"=="rl" (
  if "!TS_FILTER!"=="" (
    set "PATS=RL_Audit_Report_*.csv"
  ) else (
    set "PATS=RL_Audit_Report_!TS_FILTER!*.csv"
  )
) else (
  if "!TS_FILTER!"=="" (
    set "PATS=BRT_Audit_Report_*.csv;IND_Audit_Report_*.csv;MTS_Audit_Report_*.csv"
  ) else (
    set "PATS=BRT_Audit_Report_!TS_FILTER!*.csv;IND_Audit_Report_!TS_FILTER!*.csv;YH_Audit_Report_!TS_FILTER!*.csv;VEC_Audit_Report_!TS_FILTER!*.csv;WPBR_Audit_Report_!TS_FILTER!*.csv;PBR_Audit_Report_!TS_FILTER!*.csv;MTS_Audit_Report_!TS_FILTER!*.csv;RS_Audit_Report_!TS_FILTER!*.csv;RL_Audit_Report_!TS_FILTER!*.csv"
  )
)

set "MERGE_DIR=!MERGE_DIR!"
set "OUT_NAME=!OUT_NAME!"
set "PATS=!PATS!"
set "TS_FILTER=!TS_FILTER!"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$d = $env:MERGE_DIR;" ^
  "$patterns = @($env:PATS -split ';' | ForEach-Object { $_.Trim() } | Where-Object { $_ });" ^
  "$ts = $env:TS_FILTER;" ^
  "$files = @();" ^
  "foreach ($pat in $patterns) { $files += @(Get-ChildItem -LiteralPath $d -Filter $pat -ErrorAction SilentlyContinue) };" ^
  "$files = @($files | Sort-Object Name -Unique);" ^
  "if ($files.Count -eq 0) {" ^
  "  $msg = 'No files matching ' + ($patterns -join '/') + ' in ' + $d + '.';" ^
  "  if ($ts) {" ^
  "    $msg += ' No runs with stamp prefix ''' + $ts + '''.';" ^
  "    $hint = @(Get-ChildItem -LiteralPath $d -Filter '*_Audit_Report_*.csv' -ErrorAction SilentlyContinue |" ^
  "      Sort-Object LastWriteTime -Descending |" ^
  "      ForEach-Object {" ^
  "        if ($_.Name -match '_Audit_Report_(\d{8,})') { $Matches[1].Substring(0, [Math]::Min(8, $Matches[1].Length)) }" ^
  "      } | Select-Object -Unique -First 5);" ^
  "    if ($hint.Count -gt 0) { $msg += ' Recent stamps on disk: ' + ($hint -join ', ') + '.' }" ^
  "  };" ^
  "  Write-Error $msg; exit 1" ^
  "};" ^
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
