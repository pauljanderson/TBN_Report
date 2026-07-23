<#
.SYNOPSIS
    After rocket_brt and run_audit.ps1, copy selected latest system CSVs to stable names in drive\.

.DESCRIPTION
    BRT run: latest yyMMddHHmmss from drive\BRT_{Closed|Open|Scanner|Watchlist|Summary}_<ts>.csv only
             (not auxiliary BRT_* files such as Profile_Symbols; excludes *_RL_* mirror names).
    IND run: latest yyMMddHHmmss from IND copy stems (Closed, Open, Scanner, Watchlist, etc.).
    MTS run: latest yyMMddHHmmss from MTS_Closed|Open|Scanner|Watchlist|Summary_<ts>.csv.
    WPBR run: latest yyMMddHHmmss from WPBR_Closed|Open|Scanner|Watchlist|Summary_<ts>.csv
             (falls back to legacy PBR_* filenames if no WPBR_* yet).
    RS run: latest yyMMddHHmmss from RS_Closed|Open|Scanner|Summary_<ts>.csv.

    Rocket Launcher / audit: timestamp from drive\last_run_ts.txt (same as portfolio_audit.awk).

    Copies only:
      BRT_Closed|Open|Scanner|Watchlist|Summary_<brtTs>.csv  -> BRT_LatestRun_*.csv
      YH_Closed|Open|Scanner|Watchlist|Summary_<yhTs>.csv  -> YH_LatestRun_*.csv
      IND_Closed|Open|Scanner|Watchlist|Summary|indicators_while_held|EquityCurve_Aggressive_<indTs>.csv -> IND_LatestRun_*.csv
      MTS_Closed|Open|Scanner|Watchlist|Summary_<mtsTs>.csv  -> MTS_LatestRun_*.csv
      WPBR_Closed|Open|Scanner|Watchlist|Summary_<wpbrTs>.csv  -> WPBR_LatestRun_*.csv
      RS_Closed|Open|Scanner|Summary_<rsTs>.csv             -> RS_LatestRun_*.csv
      RL_Closed|Open|Scanner|Watchlist|Summary_<rlTs>.csv    -> RL_LatestRun_*.csv

.PARAMETER RepoRoot
    Repo root (default: this script's directory).

.PARAMETER OutputDir
    drive\ or Drive\ under repo.

.PARAMETER BrtTimestamp
    Force BRT yyMMddHHmmss (optional).

.PARAMETER IndTimestamp
    Force IND yyMMddHHmmss (optional).

.PARAMETER YhTimestamp
    Force YH yyMMddHHmmss (optional).

.PARAMETER RlTimestamp
    Force RL yyMMddHHmmss (optional).

.PARAMETER MtsTimestamp
    Force MTS yyMMddHHmmss (optional).

.PARAMETER WpbrTimestamp
    Force WPBR yyMMddHHmmss (optional).

.PARAMETER RsTimestamp
    Force RS yyMMddHHmmss (optional).
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string] $RepoRoot = "",
    [string] $OutputDir = "",
    [string] $BrtTimestamp = "",
    [string] $IndTimestamp = "",
    [string] $YhTimestamp = "",
    [string] $RlTimestamp = "",
    [string] $MtsTimestamp = "",
    [string] $WpbrTimestamp = "",
    [string] $RsTimestamp = ""
)

$ErrorActionPreference = "Stop"

if (-not $RepoRoot) { $RepoRoot = $PSScriptRoot }
if (-not $OutputDir) {
    $d1 = Join-Path $RepoRoot "drive"
    $d2 = Join-Path $RepoRoot "Drive"
    if (Test-Path -LiteralPath $d1) { $OutputDir = $d1 }
    elseif (Test-Path -LiteralPath $d2) { $OutputDir = $d2 }
    else { throw "Neither '$d1' nor '$d2' exists. Pass -OutputDir or create drive\." }
}

$BrtStems = @("Closed", "Open", "Scanner", "Watchlist", "Summary")
$YhStems = @("Closed", "Open", "Scanner", "Watchlist", "Summary")
$MtsStems = @("Closed", "Open", "Scanner", "Watchlist", "Summary")
$WpbrStems = @("Closed", "Open", "Scanner", "Watchlist", "Summary")
$RsStems = @("Closed", "Open", "Scanner", "Summary")
$IndStems = @("Closed", "Open", "Scanner", "Watchlist", "Summary", "indicators_while_held", "EquityCurve_Aggressive")
$RlStems = @("Closed", "Open", "Scanner", "Watchlist", "Summary")

function Test-IsBrtRlMirrorFile([System.IO.FileInfo]$f) {
    return ($f.BaseName -match '_RL_\d{12}$')
}

function Get-LatestTimestampFromStems {
    param(
        [string] $Dir,
        [string] $NamePrefix,
        [string[]] $Stems,
        [string] $Override
    )
    if ($Override) { return $Override.Trim() }
    $best = $null
    foreach ($stem in $Stems) {
        $pattern = "^${NamePrefix}_${stem}_(\d{12})$"
        Get-ChildItem -LiteralPath $Dir -File -ErrorAction SilentlyContinue |
            Where-Object {
                $_.Name -like "${NamePrefix}_${stem}_*.csv" -and -not (Test-IsBrtRlMirrorFile $_)
            } |
            ForEach-Object {
                if ($_.BaseName -match $pattern) {
                    $t = $Matches[1]
                    if ($null -eq $best -or [string]$t -gt [string]$best) { $best = $t }
                }
            }
    }
    if (-not $best) {
        throw "No ${NamePrefix} timestamped files for stems [$($Stems -join ', ')] under $Dir."
    }
    return $best
}

function Get-LatestBrtCoreTimestamp([string]$dir, [string]$override, [string[]]$stems) {
    return Get-LatestTimestampFromStems -Dir $dir -NamePrefix "BRT" -Stems $stems -Override $override
}

function Get-LatestIndCoreTimestamp([string]$dir, [string]$override, [string[]]$stems) {
    return Get-LatestTimestampFromStems -Dir $dir -NamePrefix "IND" -Stems $stems -Override $override
}

function Get-LatestYhCoreTimestamp([string]$dir, [string]$override, [string[]]$stems) {
    return Get-LatestTimestampFromStems -Dir $dir -NamePrefix "YH" -Stems $stems -Override $override
}

function Get-LatestMtsCoreTimestamp([string]$dir, [string]$override, [string[]]$stems) {
    return Get-LatestTimestampFromStems -Dir $dir -NamePrefix "MTS" -Stems $stems -Override $override
}

function Get-LatestWpbrCoreTimestamp([string]$dir, [string]$override, [string[]]$stems) {
    # Prefer newest among WPBR_* and legacy PBR_* filenames.
    if ($override) { return $override.Trim() }
    $best = $null
    foreach ($prefix in @("WPBR", "PBR")) {
        try {
            $t = Get-LatestTimestampFromStems -Dir $dir -NamePrefix $prefix -Stems $stems -Override ""
            if ($null -eq $best -or [string]$t -gt [string]$best) { $best = $t }
        } catch {
            # prefix may be absent
        }
    }
    if (-not $best) {
        throw "No WPBR/PBR timestamped files for stems [$($stems -join ', ')] under $dir."
    }
    return $best
}

function Get-LatestRsCoreTimestamp([string]$dir, [string]$override, [string[]]$stems) {
    return Get-LatestTimestampFromStems -Dir $dir -NamePrefix "RS" -Stems $stems -Override $override
}

function Get-RlTimestamp([string]$dir, [string]$override) {
    if ($override) { return $override.Trim() }
    $f = Join-Path $dir "last_run_ts.txt"
    if (-not (Test-Path -LiteralPath $f)) { throw "Missing last_run_ts.txt under $dir (run run_audit.ps1 first)." }
    $ts = (Get-Content -LiteralPath $f -Raw).Trim()
    if ($ts -notmatch '^\d{12}$') { throw "last_run_ts.txt should be 12-digit yyMMddHHmmss; got: '$ts'" }
    return $ts
}

function Copy-RunCsv {
    param(
        [string] $SourcePrefix,
        [string] $Stem,
        [string] $Timestamp,
        [string] $DestPrefix,
        [string] $Dir
    )
    $srcName = "{0}_{1}_{2}.csv" -f $SourcePrefix, $Stem, $Timestamp
    $destName = "{0}_{1}.csv" -f $DestPrefix, $Stem
    $src = Join-Path $Dir $srcName
    $dest = Join-Path $Dir $destName
    if (-not (Test-Path -LiteralPath $src)) {
        Write-Warning "Missing $srcName (skipped)."
        return
    }
    if ($PSCmdlet.ShouldProcess($src, "Copy -> $destName")) {
        Copy-Item -LiteralPath $src -Destination $dest -Force
        Write-Host "  $destName" -ForegroundColor Gray
    }
}

$brtTs = Get-LatestBrtCoreTimestamp $OutputDir $BrtTimestamp $BrtStems
$yhTs = $null
try {
    $yhTs = Get-LatestYhCoreTimestamp $OutputDir $YhTimestamp $YhStems
} catch {
    Write-Warning $_.Exception.Message
}
$indTs = $null
try {
    $indTs = Get-LatestIndCoreTimestamp $OutputDir $IndTimestamp $IndStems
} catch {
    Write-Warning $_.Exception.Message
}
$mtsTs = $null
try {
    $mtsTs = Get-LatestMtsCoreTimestamp $OutputDir $MtsTimestamp $MtsStems
} catch {
    Write-Warning $_.Exception.Message
}
$wpbrTs = $null
$wpbrSourcePrefix = "WPBR"
try {
    $wpbrTs = Get-LatestWpbrCoreTimestamp $OutputDir $WpbrTimestamp $WpbrStems
    # Detect whether the winning timestamp came from legacy PBR_* files.
    if (-not $WpbrTimestamp) {
        $hasWpbr = $false
        foreach ($stem in $WpbrStems) {
            $probe = Join-Path $OutputDir ("WPBR_{0}_{1}.csv" -f $stem, $wpbrTs)
            if (Test-Path -LiteralPath $probe) { $hasWpbr = $true; break }
        }
        if (-not $hasWpbr) { $wpbrSourcePrefix = "PBR" }
    }
} catch {
    Write-Warning $_.Exception.Message
}
$rsTs = $null
try {
    $rsTs = Get-LatestRsCoreTimestamp $OutputDir $RsTimestamp $RsStems
} catch {
    Write-Warning $_.Exception.Message
}
$rlTs = Get-RlTimestamp $OutputDir $RlTimestamp

Write-Host "Drive:       $OutputDir" -ForegroundColor Cyan
Write-Host "BRT core ts: $brtTs" -ForegroundColor Yellow
if ($yhTs) { Write-Host "YH core ts:  $yhTs" -ForegroundColor Yellow }
if ($indTs) { Write-Host "IND core ts: $indTs" -ForegroundColor Yellow }
if ($mtsTs) { Write-Host "MTS core ts: $mtsTs" -ForegroundColor Yellow }
if ($wpbrTs) { Write-Host "WPBR core ts: $wpbrTs" -ForegroundColor Yellow }
if ($rsTs) { Write-Host "RS core ts:  $rsTs" -ForegroundColor Yellow }
Write-Host "RL audit ts: $rlTs" -ForegroundColor Yellow

Write-Host "BRT_LatestRun:" -ForegroundColor Cyan
foreach ($stem in $BrtStems) {
    Copy-RunCsv -SourcePrefix "BRT" -Stem $stem -Timestamp $brtTs -DestPrefix "BRT_LatestRun" -Dir $OutputDir
}

if ($yhTs) {
    Write-Host "YH_LatestRun:" -ForegroundColor Cyan
    foreach ($stem in $YhStems) {
        Copy-RunCsv -SourcePrefix "YH" -Stem $stem -Timestamp $yhTs -DestPrefix "YH_LatestRun" -Dir $OutputDir
    }
}

if ($indTs) {
    Write-Host "IND_LatestRun:" -ForegroundColor Cyan
    foreach ($stem in $IndStems) {
        Copy-RunCsv -SourcePrefix "IND" -Stem $stem -Timestamp $indTs -DestPrefix "IND_LatestRun" -Dir $OutputDir
    }
}

if ($mtsTs) {
    Write-Host "MTS_LatestRun:" -ForegroundColor Cyan
    foreach ($stem in $MtsStems) {
        Copy-RunCsv -SourcePrefix "MTS" -Stem $stem -Timestamp $mtsTs -DestPrefix "MTS_LatestRun" -Dir $OutputDir
    }
}

if ($wpbrTs) {
    Write-Host "WPBR_LatestRun:" -ForegroundColor Cyan
    foreach ($stem in $WpbrStems) {
        Copy-RunCsv -SourcePrefix $wpbrSourcePrefix -Stem $stem -Timestamp $wpbrTs -DestPrefix "WPBR_LatestRun" -Dir $OutputDir
    }
}

if ($rsTs) {
    Write-Host "RS_LatestRun:" -ForegroundColor Cyan
    foreach ($stem in $RsStems) {
        Copy-RunCsv -SourcePrefix "RS" -Stem $stem -Timestamp $rsTs -DestPrefix "RS_LatestRun" -Dir $OutputDir
    }
}

Write-Host "RL_LatestRun:" -ForegroundColor Cyan
foreach ($stem in $RlStems) {
    Copy-RunCsv -SourcePrefix "RL" -Stem $stem -Timestamp $rlTs -DestPrefix "RL_LatestRun" -Dir $OutputDir
}

Write-Host "Done." -ForegroundColor Green
