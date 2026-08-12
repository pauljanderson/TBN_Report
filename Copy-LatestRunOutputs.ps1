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
    RS run: latest yyMMddHHmmss from RS_Closed|Open|Scanner|Watchlist|Summary_<ts>.csv.
    SB run: prefer newest *production* yyMMddHHmmss from SB_Closed|Open|Watchlist|Summary|RejectedFills|Audit_Report|EquityCurve|Correlation|Correlation_Pairs_<ts>.csv
             (standalone StockBee engine; also writes SB_LatestRun_* itself).
             Production preference: Audit entry_start_date empty (skips AB/research window stamps
             such as hint AB 06_false_start_2024 that also land under drive\ and would otherwise win by stamp).
             Override with -SbTimestamp when an explicit research stamp must be copied.
    MVCP run: latest yyMMddHHmmss from MVCP_Closed|Open|Watchlist|Summary|Audit_Report|EquityCurve|Correlation|Correlation_Pairs_<ts>.csv
             (Minervini VCP; also writes MVCP_LatestRun_* itself).
    VZ run: latest yyMMddHHmmss from VZ_Closed|Open|Watchlist|Summary|Audit_Report|EquityCurve|Correlation|Correlation_Pairs_<ts>.csv
             (Volume Zone research sleeve; also writes VZ_LatestRun_* itself).

    Rocket Launcher / audit: prefer newest RL_Closed|Open|Scanner|Watchlist|Summary_<ts>.csv;
             fall back to drive\last_run_ts.txt (AWK/Python RL still write this).

    Copies only:
      BRT_Closed|Open|Scanner|Watchlist|Summary_<brtTs>.csv  -> BRT_LatestRun_*.csv
      YH_Closed|Open|Scanner|Watchlist|Summary_<yhTs>.csv  -> YH_LatestRun_*.csv
      IND_Closed|Open|Scanner|Watchlist|Summary|indicators_while_held|EquityCurve_Aggressive_<indTs>.csv -> IND_LatestRun_*.csv
      MTS_Closed|Open|Scanner|Watchlist|Summary_<mtsTs>.csv  -> MTS_LatestRun_*.csv
      WPBR_Closed|Open|Scanner|Watchlist|Summary_<wpbrTs>.csv  -> WPBR_LatestRun_*.csv
      RS_Closed|Open|Scanner|Watchlist|Summary_<rsTs>.csv   -> RS_LatestRun_*.csv
      SB_Closed|Open|Watchlist|Summary|RejectedFills|Audit_Report|EquityCurve|Correlation|Correlation_Pairs_<sbTs>.csv -> SB_LatestRun_*.csv
      MVCP_Closed|Open|Watchlist|Summary|Audit_Report|EquityCurve|Correlation|Correlation_Pairs_<mvcpTs>.csv -> MVCP_LatestRun_*.csv
      VZ_Closed|Open|Watchlist|Summary|Audit_Report|EquityCurve|Correlation|Correlation_Pairs_<vzTs>.csv -> VZ_LatestRun_*.csv
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

.PARAMETER SbTimestamp
    Force SB yyMMddHHmmss (optional).

.PARAMETER MvcpTimestamp
    Force MVCP yyMMddHHmmss (optional).

.PARAMETER VzTimestamp
    Force VZ yyMMddHHmmss (optional).
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
    [string] $RsTimestamp = "",
    [string] $SbTimestamp = "",
    [string] $MvcpTimestamp = "",
    [string] $VzTimestamp = ""
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
$RsStems = @("Closed", "Open", "Scanner", "Watchlist", "Summary")
$SbStems = @("Closed", "Open", "Watchlist", "Summary", "RejectedFills", "Audit_Report", "EquityCurve", "Correlation", "Correlation_Pairs")
$MvcpStems = @("Closed", "Open", "Watchlist", "Summary", "Audit_Report", "EquityCurve", "Correlation", "Correlation_Pairs")
$VzStems = @("Closed", "Open", "Watchlist", "Summary", "Audit_Report", "EquityCurve", "Correlation", "Correlation_Pairs")
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

function Get-SbAuditEntryStartDate([string]$dir, [string]$stamp) {
    # Audit CSVs can have duplicate column names (Import-Csv throws AlreadyPresentPSMemberInfo).
    # Use TextFieldParser so we can still read entry_start_date.
    $audit = Join-Path $dir ("SB_Audit_Report_{0}.csv" -f $stamp)
    if (-not (Test-Path -LiteralPath $audit)) { return $null }
    try {
        Add-Type -AssemblyName Microsoft.VisualBasic -ErrorAction SilentlyContinue | Out-Null
        $parser = New-Object Microsoft.VisualBasic.FileIO.TextFieldParser($audit)
        try {
            $parser.TextFieldType = [Microsoft.VisualBasic.FileIO.FieldType]::Delimited
            $parser.SetDelimiters(",")
            $parser.HasFieldsEnclosedInQuotes = $true
            if ($parser.EndOfData) { return $null }
            $header = @($parser.ReadFields())
            $idx = [array]::IndexOf($header, "entry_start_date")
            if ($idx -lt 0) { return $null }
            if ($parser.EndOfData) { return $null }
            $fields = @($parser.ReadFields())
            if ($idx -ge $fields.Count) { return $null }
            return [string]$fields[$idx]
        } finally {
            $parser.Close()
        }
    } catch {
        return $null
    }
}

function Test-SbStampLooksProduction([string]$dir, [string]$stamp) {
    # Production DailyRun / run_sb.bat leave entry_start_date blank.
    # Hint-AB / research arms that set -v entry_start_date=... must not win LatestRun.
    $es = Get-SbAuditEntryStartDate -dir $dir -stamp $stamp
    if ($null -eq $es) {
        # No Audit column / unreadable — allow (legacy stamps); Closed still must exist.
        return $true
    }
    return [string]::IsNullOrWhiteSpace($es)
}

function Get-LatestSbCoreTimestamp([string]$dir, [string]$override, [string[]]$stems) {
    if ($override) { return $override.Trim() }

    $all = New-Object System.Collections.Generic.HashSet[string]
    foreach ($stem in $stems) {
        $pattern = "^SB_${stem}_(\d{12})$"
        Get-ChildItem -LiteralPath $dir -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -like "SB_${stem}_*.csv" } |
            ForEach-Object {
                if ($_.BaseName -match $pattern) { [void]$all.Add($Matches[1]) }
            }
    }
    if ($all.Count -eq 0) {
        throw "No SB timestamped files for stems [$($stems -join ', ')] under $dir."
    }

    # Newest-first: skip research-window stamps until a production (blank entry_start_date) hit.
    $skipped = @()
    foreach ($t in ($all | Sort-Object -Descending)) {
        if (Test-SbStampLooksProduction -dir $dir -stamp $t) {
            if ($skipped.Count -gt 0) {
                Write-Warning ("SB LatestRun: skipping research/window stamp(s): {0}" -f ($skipped -join ", "))
                Write-Host ("SB LatestRun: preferring production stamp {0} (empty entry_start_date)" -f $t) -ForegroundColor Yellow
            }
            return $t
        }
        $es = Get-SbAuditEntryStartDate -dir $dir -stamp $t
        $skipped += ("{0}(entry_start_date={1})" -f $t, $es)
    }
    Write-Warning ("SB LatestRun: no stamp with empty entry_start_date (checked: {0}); falling back to newest stamp overall." -f ($skipped -join ", "))
    return ($all | Sort-Object -Descending | Select-Object -First 1)
}

function Get-LatestMvcpCoreTimestamp([string]$dir, [string]$override, [string[]]$stems) {
    return Get-LatestTimestampFromStems -Dir $dir -NamePrefix "MVCP" -Stems $stems -Override $override
}

function Get-LatestVzCoreTimestamp([string]$dir, [string]$override, [string[]]$stems) {
    return Get-LatestTimestampFromStems -Dir $dir -NamePrefix "VZ" -Stems $stems -Override $override
}

function Get-RlTimestamp([string]$dir, [string]$override, [string[]]$stems) {
    if ($override) { return $override.Trim() }
    # Prefer newest RL_* stamped cores so later SB/MVCP runs that overwrite last_run_ts.txt
    # do not steal the RL LatestRun alias.
    try {
        return Get-LatestTimestampFromStems -Dir $dir -NamePrefix "RL" -Stems $stems -Override ""
    } catch {
        # fall through to legacy last_run_ts.txt
    }
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
$sbTs = $null
try {
    $sbTs = Get-LatestSbCoreTimestamp $OutputDir $SbTimestamp $SbStems
} catch {
    Write-Warning $_.Exception.Message
}
$mvcpTs = $null
try {
    $mvcpTs = Get-LatestMvcpCoreTimestamp $OutputDir $MvcpTimestamp $MvcpStems
} catch {
    Write-Warning $_.Exception.Message
}
$vzTs = $null
try {
    $vzTs = Get-LatestVzCoreTimestamp $OutputDir $VzTimestamp $VzStems
} catch {
    Write-Warning $_.Exception.Message
}
$rlTs = Get-RlTimestamp $OutputDir $RlTimestamp $RlStems

Write-Host "Drive:       $OutputDir" -ForegroundColor Cyan
Write-Host "BRT core ts: $brtTs" -ForegroundColor Yellow
if ($yhTs) { Write-Host "YH core ts:  $yhTs" -ForegroundColor Yellow }
if ($indTs) { Write-Host "IND core ts: $indTs" -ForegroundColor Yellow }
if ($mtsTs) { Write-Host "MTS core ts: $mtsTs" -ForegroundColor Yellow }
if ($wpbrTs) { Write-Host "WPBR core ts: $wpbrTs" -ForegroundColor Yellow }
if ($rsTs) { Write-Host "RS core ts:  $rsTs" -ForegroundColor Yellow }
if ($sbTs) { Write-Host "SB core ts:  $sbTs" -ForegroundColor Yellow }
if ($mvcpTs) { Write-Host "MVCP core ts: $mvcpTs" -ForegroundColor Yellow }
if ($vzTs) { Write-Host "VZ core ts:  $vzTs" -ForegroundColor Yellow }
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

if ($sbTs) {
    Write-Host "SB_LatestRun:" -ForegroundColor Cyan
    foreach ($stem in $SbStems) {
        Copy-RunCsv -SourcePrefix "SB" -Stem $stem -Timestamp $sbTs -DestPrefix "SB_LatestRun" -Dir $OutputDir
    }
}

if ($mvcpTs) {
    Write-Host "MVCP_LatestRun:" -ForegroundColor Cyan
    foreach ($stem in $MvcpStems) {
        Copy-RunCsv -SourcePrefix "MVCP" -Stem $stem -Timestamp $mvcpTs -DestPrefix "MVCP_LatestRun" -Dir $OutputDir
    }
}

if ($vzTs) {
    Write-Host "VZ_LatestRun:" -ForegroundColor Cyan
    foreach ($stem in $VzStems) {
        Copy-RunCsv -SourcePrefix "VZ" -Stem $stem -Timestamp $vzTs -DestPrefix "VZ_LatestRun" -Dir $OutputDir
    }
}

Write-Host "RL_LatestRun:" -ForegroundColor Cyan
foreach ($stem in $RlStems) {
    Copy-RunCsv -SourcePrefix "RL" -Stem $stem -Timestamp $rlTs -DestPrefix "RL_LatestRun" -Dir $OutputDir
}

Write-Host "Done." -ForegroundColor Green
