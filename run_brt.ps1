<#
.SYNOPSIS
    Runs the Rocket BRT backtest (rocket_brt.py). Regression check is built into
    rocket_brt.py and runs automatically after each full backtest.

.DESCRIPTION
    Runs rocket_brt.py over all symbols. rocket_brt.py runs BRTRegressionCheck.ps1
    at the end to compare output to the previous run. If any output differs, exit
    code 1. Use -SkipRegressionCheck to skip the regression step.

.PARAMETER SkipRegressionCheck
    If set, pass --no-regression to rocket_brt.py (skip regression comparison).

.PARAMETER AllowRegression
    Not used; regression fail-on-exit is controlled by BRTRegressionCheck.ps1.

.PARAMETER Workers
    Number of parallel workers for rocket_brt (0=sequential). Use -w 4 for 4 workers.

.PARAMETER DataDir
    Data directory for CSVs (default: data/newdata/data).

.PARAMETER Symbol
    Single symbol to run (e.g. NVDA). When set, only this symbol is backtested and chart/zone debug can be written.

.PARAMETER PrintZones
    Write BRT_ZONES_* and BRT_ZONES_ENTRIES_* CSVs for zone/overlap debug. Use with -Symbol.

.PARAMETER Variable
    Pass config overrides to rocket_brt as key=value. Multiple -v args or comma-separated. E.g. -v touch_threshold=6 -v min_touch_count=5.

.PARAMETER Profile
    Enable timing profile (yfinance, correlation, equity metrics, CSV writes).

.PARAMETER Cprofile
    Pass --cprofile to rocket_brt (cProfile stats for run_brt_backtest only). Requires -Symbol.
    Optional: -CprofileOut for a custom .prof path.

.PARAMETER CprofileOut
    Pass --cprofile-out PATH to rocket_brt (used with -Cprofile).

.PARAMETER CprofileSheetMagicTouch
    Pass --cprofile-sheet-magic-touch (cProfile only the sheet AR/AW block in the bar loop). Requires -Symbol.

.PARAMETER CprofileSheetMagicTouchOut
    Optional --cprofile-sheet-magic-touch-out PATH for the .prof file.

.PARAMETER CprofilePendingSheetPrep
    Pass --cprofile-pending-sheet-prep (cProfile for the per-bar AQ/AK prep block). Requires -Symbol.

.PARAMETER CprofilePendingSheetPrepOut
    Optional --cprofile-pending-sheet-prep-out PATH for the .prof file.

.PARAMETER SkipEquityMetrics
    Skip Max_Drawdown / underwater metrics (~30–40s saved on large runs).

.PARAMETER EmitWouldHave
    Pass --emit-would-have to rocket_brt (write BRT_WouldHave_<ts>.csv for DrawdownCalc --show-would-have).

.PARAMETER PlaySound
    Pass --play-sound to rocket_brt: system beep when the Python run finishes (success or regression failure).

.PARAMETER Aggressive
    Pass --aggressive to rocket_brt (aggressive equity sizing mode for drawdown/equity metrics).

.PARAMETER UseOG
    If set, run the original engine (stock_analysis/rocket_brt_og.py) instead of stock_analysis/rocket_brt.py.

.EXAMPLE
    .\run_brt.ps1
    .\run_brt.ps1 -SkipRegressionCheck
    .\run_brt.ps1 -Symbol NVDA -PrintZones
    .\run_brt.ps1 -Workers 4
    .\run_brt.ps1 -v touch_threshold=6 -w 8
    .\run_brt.ps1 -Variable "touch_threshold=6","min_touch_count=5" -Workers 8
    .\run_brt.ps1 -w 5 -v "stop_pct=0","target_pct=0","atr_target=10","atr_stop=3","atr_increment=5"
    .\run_brt.ps1 -w 6 -Profile -EmitWouldHave -v "touch_threshold=2"
    .\run_brt.ps1 -w 5 -Profile -PlaySound
    .\run_brt.ps1 -Symbol FSI -Profile -Cprofile
#>
param(
    [switch] $SkipRegressionCheck,
    [switch] $AllowRegression,
    [switch] $UseOG,
    [Parameter(ValueFromPipelineByPropertyName = $true)]
    [Alias("w")]
    [int] $Workers = 0,
    [string] $DataDir = "data/newdata/data",
    [string] $Symbol = "",
    [switch] $PrintZones,
    [Parameter(ValueFromPipelineByPropertyName = $true)]
    [Alias("v")]
    [string[]] $Variable = @(),
    [switch] $Profile,
    [switch] $Cprofile,
    [string] $CprofileOut = "",
    [switch] $CprofileSheetMagicTouch,
    [string] $CprofileSheetMagicTouchOut = "",
    [switch] $CprofilePendingSheetPrep,
    [string] $CprofilePendingSheetPrepOut = "",
    [switch] $SkipEquityMetrics,
    [switch] $EmitWouldHave,
    [switch] $PlaySound,
    [switch] $Aggressive
)

$ErrorActionPreference = "Stop"
$RepoRoot = $PSScriptRoot
$DriveDir = Join-Path $RepoRoot "drive"
$BrtScriptRel = if ($UseOG) { "stock_analysis\rocket_brt_og.py" } else { "stock_analysis\rocket_brt.py" }
$BrtScript = Join-Path $RepoRoot $BrtScriptRel

if (-not (Test-Path $BrtScript)) {
    Write-Host "BRT script not found: $BrtScript" -ForegroundColor Red
    exit 1
}

if ($DataDir -match '^\-') {
    Write-Host "Data path looks like a flag: $DataDir" -ForegroundColor Red
    Write-Host "Use -Profile for profiling (e.g. -Profile or -profile), not --profile as a positional. Example: .\run_brt.ps1 -w 6 -Profile -v `"touch_threshold=2`"" -ForegroundColor Yellow
    exit 1
}
$dataPath = if ([System.IO.Path]::IsPathRooted($DataDir)) { $DataDir } else { Join-Path $RepoRoot $DataDir }
if (-not (Test-Path $dataPath)) {
    Write-Host "Data path not found: $dataPath" -ForegroundColor Red
    exit 1
}

if ($Cprofile -and -not $Symbol) {
    Write-Host "-Cprofile requires -Symbol (single-symbol run). Example: .\run_brt.ps1 -Symbol FSI -Profile -Cprofile" -ForegroundColor Red
    exit 1
}

if ($CprofileSheetMagicTouch -and -not $Symbol) {
    Write-Host "-CprofileSheetMagicTouch requires -Symbol. Example: .\run_brt.ps1 -Symbol NVDA -CprofileSheetMagicTouch" -ForegroundColor Red
    exit 1
}
if ($CprofilePendingSheetPrep -and -not $Symbol) {
    Write-Host "-CprofilePendingSheetPrep requires -Symbol. Example: .\run_brt.ps1 -Symbol NVDA -CprofilePendingSheetPrep" -ForegroundColor Red
    exit 1
}

Set-Location $RepoRoot

Write-Host "Running Rocket BRT..." -ForegroundColor Cyan
if ($UseOG) {
    Write-Host "  Engine: OG (rocket_brt_og.py)" -ForegroundColor Gray
} else {
    Write-Host "  Engine: simplified (rocket_brt.py)" -ForegroundColor Gray
}
Write-Host "  Script: $BrtScript" -ForegroundColor Gray
Write-Host "  Data:   $dataPath" -ForegroundColor Gray
Write-Host "  Output: $DriveDir" -ForegroundColor Gray
if ($Workers -gt 0) {
    Write-Host "  Workers: $Workers" -ForegroundColor Gray
}
if ($Symbol) {
    Write-Host "  Symbol:  $Symbol (single-symbol mode)" -ForegroundColor Gray
}
if ($PrintZones) {
    Write-Host "  PrintZones: enabled (BRT_ZONES_* files)" -ForegroundColor Gray
}
if ($Profile) {
    Write-Host "  Profile: enabled (timing for yfinance, correlation, equity, writes)" -ForegroundColor Gray
}
if ($CprofileSheetMagicTouch) {
    Write-Host "  CprofileSheetMagicTouch: cProfile for bt_loop_sheet_magic_touch only -> drive/BRT_cProfile_sheet_magic_touch_<SYM>_<ts>.prof" -ForegroundColor Gray
}
if ($CprofilePendingSheetPrep) {
    Write-Host "  CprofilePendingSheetPrep: cProfile for bt_loop_pending_sheet_prep only -> drive/BRT_cProfile_pending_sheet_prep_<SYM>_<ts>.prof" -ForegroundColor Gray
}
if ($SkipEquityMetrics) {
    Write-Host "  SkipEquityMetrics: enabled (no Max_Drawdown / underwater)" -ForegroundColor Gray
}
if ($EmitWouldHave) {
    Write-Host "  EmitWouldHave: enabled (BRT_WouldHave_<ts>.csv for DrawdownCalc)" -ForegroundColor Gray
}
if ($Aggressive) {
    Write-Host "  Aggressive: enabled (aggressive equity sizing for drawdown/equity)" -ForegroundColor Gray
}
if ($Variable -and $Variable.Count -gt 0) {
    Write-Host "  Variables:  $($Variable -join ', ')" -ForegroundColor Gray
}
Write-Host ""

Write-Host "------------------------------------------------------------" -ForegroundColor Gray
Write-Host ("BRT START: " + (Get-Date -Format "HH:mm:ss")) -ForegroundColor Gray
Write-Host "------------------------------------------------------------" -ForegroundColor Gray

$brtStart = Get-Date

$pythonArgs = @($BrtScriptRel.Replace("\","/"), $DataDir, "-o", "drive")
if ($Symbol) {
    $pythonArgs += "-s", $Symbol
}
if ($Workers -gt 0) {
    $pythonArgs += "-w", $Workers
}
if ($SkipRegressionCheck) {
    $pythonArgs += "--no-regression"
}
if ($SkipEquityMetrics) {
    $pythonArgs += "--no-equity-metrics"
}
if ($PrintZones) {
    $pythonArgs += "--print-zones"
}
if ($Profile) {
    $pythonArgs += "--profile"
}
if ($Cprofile) {
    $pythonArgs += "--cprofile"
    if ($CprofileOut) {
        $pythonArgs += "--cprofile-out", $CprofileOut
    }
}
if ($CprofileSheetMagicTouch) {
    $pythonArgs += "--cprofile-sheet-magic-touch"
    if ($CprofileSheetMagicTouchOut) {
        $pythonArgs += "--cprofile-sheet-magic-touch-out", $CprofileSheetMagicTouchOut
    }
}
if ($CprofilePendingSheetPrep) {
    $pythonArgs += "--cprofile-pending-sheet-prep"
    if ($CprofilePendingSheetPrepOut) {
        $pythonArgs += "--cprofile-pending-sheet-prep-out", $CprofilePendingSheetPrepOut
    }
}
if ($EmitWouldHave) {
    $pythonArgs += "--emit-would-have"
}
if ($PlaySound) {
    $pythonArgs += "--play-sound"
}
if ($Aggressive) {
    $pythonArgs += "--aggressive"
}
foreach ($kv in $Variable) {
    if ([string]::IsNullOrWhiteSpace($kv)) { continue }
    $pythonArgs += "--set", $kv.Trim()
}
# YH mode defaults (override with -v brt_zones=true and/or -v yh_zones=false).
$hasYhZones = $false
$hasBrtZones = $false
foreach ($kv in $Variable) {
    if ($kv -match '^\s*yh_zones\s*=') { $hasYhZones = $true }
    if ($kv -match '^\s*brt_zones\s*=') { $hasBrtZones = $true }
}
if (-not $hasYhZones) {
    $pythonArgs += "--set", "yh_zones=true"
}
if (-not $hasBrtZones) {
    $pythonArgs += "--set", "brt_zones=false"
}
# YH sheet-parity defaults (override with -v).
$hasMaxPos = $false
$hasSpy1y = $false
$hasTooHigh = $false
foreach ($kv in $Variable) {
    if ($kv -match '^\s*max_positions\s*=') { $hasMaxPos = $true }
    if ($kv -match '^\s*min_spy_compare_1y_at_trigger\s*=') { $hasSpy1y = $true }
    if ($kv -match '^\s*too_high_multiplier\s*=') { $hasTooHigh = $true }
}
if (-not $hasMaxPos) {
    $pythonArgs += "--set", "max_positions=16"
}
if (-not $hasSpy1y) {
    $pythonArgs += "--set", "min_spy_compare_1y_at_trigger=-1000"
}
if (-not $hasTooHigh) {
    $pythonArgs += "--set", "too_high_multiplier=0"
}
if ($Variable -and $Variable.Count -gt 0) {
    Write-Host "  Command: python $($pythonArgs -join ' ')" -ForegroundColor DarkGray
}
& python @pythonArgs

$brtExit = $LASTEXITCODE
$brtEnd = Get-Date
$durationSec = [math]::Round(($brtEnd - $brtStart).TotalSeconds, 1)

Write-Host ""
Write-Host "------------------------------------------------------------" -ForegroundColor Gray
Write-Host ("BRT END:   " + $brtEnd.ToString("HH:mm:ss") + " (duration: $durationSec s)") -ForegroundColor Gray
Write-Host "------------------------------------------------------------" -ForegroundColor Gray

if ($brtExit -ne 0) {
    Write-Host "BRT failed (exit code $brtExit)." -ForegroundColor Red
    exit $brtExit
}

Write-Host ""
Write-Host "BRT completed successfully." -ForegroundColor Green
Write-Host ""

# Regression check is built into rocket_brt.py and runs automatically.
# SkipRegressionCheck passes --no-regression to skip it.
exit $brtExit
