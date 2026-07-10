<#
.SYNOPSIS
    Convenience wrapper to run the original Rocket BRT engine (rocket_brt_og.py).

.DESCRIPTION
    Calls run_brt.ps1 with -UseOG and passes through all other arguments unchanged.

.EXAMPLE
    .\run_brt_og.ps1
    .\run_brt_og.ps1 -Symbol NVDA -w 4 -Profile -v "touch_threshold=2"
#>

$ErrorActionPreference = "Stop"
$RepoRoot = $PSScriptRoot
$Runner = Join-Path $RepoRoot "run_brt.ps1"

if (-not (Test-Path $Runner)) {
    Write-Host "Runner not found: $Runner" -ForegroundColor Red
    exit 1
}

& $Runner -UseOG @args
exit $LASTEXITCODE

