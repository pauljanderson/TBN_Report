<#
.SYNOPSIS
    Runs the portfolio audit (portfolio_audit.awk) and then compares output to the
    previous run to detect regressions.

.DESCRIPTION
    This is the recommended way to run the audit when you want automatic regression
    checking. It runs the portfolio audit AWK script, then RegressionCheck.ps1
    in the output directory. If any output file differs from the previous run, the
    script exits with code 1 and writes a detailed report.

    For faster audits, pre-fill SMA columns on ticker CSVs (see stock_analysis/precompute_csv_smas.py).
    After the BRT mirror step, ``RL_Correlation_<ts>.csv`` is written (same shape as BRT correlation: drivers vs PNL %).
    The mirror step runs Python. The Microsoft Store places ``python.exe`` / ``python3.exe`` *stubs* and the
    working ``py.exe`` launcher under ``...\WindowsApps\``; only the stub names are avoided when resolving a full path.
    Override with ``PYTHON_EXE`` if needed. Last resort: unqualified ``py -3`` (same as an interactive shell).

    When you pass ``-s`` and the file ``data\watchlist.txt`` exists in the repo, those tickers are merged into
    the symbol filter (deduped). Remove or rename that file to disable. Use ``-WatchlistFile`` for an additional list.

.PARAMETER SkipRegressionCheck
    If set, only run the audit and do not run the regression comparison.

.PARAMETER AllowRegression
    If set, run the regression check but do not exit with 1 when differences are found
    (report is still generated).

.PARAMETER Instrument
    If set, enables throughput instrumentation (instrument.txt, per-symbol timing) for performance checking.

.PARAMETER SkipTrim
    If set, skips trim_working_set() (saves ~13s in two-pass mode; use for faster runs).

.PARAMETER WatchlistFile
    Optional path to a text file of extra tickers (one per line, or comma/space-separated).
    Lines starting with # are ignored. Merged with -s into the symbol filter (deduped).

.PARAMETER NoHeartbeat
    If set, disables periodic console lines during the AWK phase (by default the script prints
    a short heartbeat every 45s while gawk runs; uses the main thread so lines appear immediately).

.PARAMETER RLTrailProfit
    Optional. Passed to gawk as -v RL_TRAIL_PROFIT=... (e.g. 0.14). Omit to use portfolio_audit.awk default.

.PARAMETER RLTrailStop
    Optional. -v RL_TRAIL_STOP=... (e.g. 0 or 0.045). Locked stop = entry * (1 + this) once trail arms.

.PARAMETER RLTrailProfit2
    Optional. -v RL_TRAIL_PROFIT2=...

.PARAMETER RLTrailStop2
    Optional. -v RL_TRAIL_STOP2=...

.EXAMPLE
    .\run_audit.ps1
    .\run_audit.ps1 -SkipRegressionCheck
    .\run_audit.ps1 -AllowRegression
    .\run_audit.ps1 -Instrument
    .\run_audit.ps1 -Instrument -SkipTrim
    .\run_audit.ps1 -s "AAPL,MSFT,NVDA"
    .\run_audit.ps1 -s AAPL,MSFT,NVDA
    .\run_audit.ps1 -WatchlistFile .\my_tickers.txt
    .\run_audit.ps1 -s "AAPL" -RLTrailProfit 0 -RLTrailStop 0 -RLTrailProfit2 0 -RLTrailStop2 0
#>
param(
    [switch] $SkipRegressionCheck,
    [switch] $AllowRegression,
    [switch] $Instrument,
    [switch] $SkipTrim,
    [Alias("s")]
    [string[]] $Symbols = @(),
    [string] $WatchlistFile = "",
    [string] $RLTrailProfit = "",
    [string] $RLTrailStop = "",
    [string] $RLTrailProfit2 = "",
    [string] $RLTrailStop2 = "",
    [switch] $NoHeartbeat
)

$ErrorActionPreference = "Stop"
$RepoRoot = $PSScriptRoot
$DriveDir = Join-Path $RepoRoot "drive"
$AwkScript = Join-Path $RepoRoot "stock_analysis\portfolio_audit.awk"
$RegressionScript = Join-Path $DriveDir "RegressionCheck.ps1"

# Inputs: SPY first (so benchmark loads before tickers), then ticker CSVs. History file no longer required.
# Use forward slashes: Git/MSYS2 gawk treats backslashes as escapes (e.g. \n=newline), which corrupts paths.
$SpyFile = "data/newdata/data/SPY.csv"
$DataGlob = "data/newdata/data/*.csv"

function ConvertTo-UnixPath([string]$Path) {
    return ($Path -replace '\\', '/')
}

# PowerShell treats unquoted commas as separate arguments (-s AAPL,MSFT binds as two strings).
# A [string] parameter would coerce that to one value with spaces, breaking CSV lookup - use [string[]] and merge here.
function Expand-TickerSymbols([string[]]$Raw) {
    if (-not $Raw -or $Raw.Count -eq 0) { return @() }
    $out = New-Object System.Collections.Generic.List[string]
    $seen = @{}
    foreach ($chunk in $Raw) {
        if ($null -eq $chunk) { continue }
        $c = ([string]$chunk).Trim()
        if ($c.Length -eq 0) { continue }
        $pieces = @()
        if ($c.IndexOf([char]',') -ge 0) {
            $pieces = @($c.Split(',', [StringSplitOptions]::RemoveEmptyEntries) | ForEach-Object { $_.Trim() })
        } elseif ($c -match '\s') {
            $pieces = @($c -split '\s+', [StringSplitOptions]::RemoveEmptyEntries | ForEach-Object { $_.Trim() })
        } else {
            $pieces = @($c)
        }
        foreach ($p in $pieces) {
            if ([string]::IsNullOrWhiteSpace($p)) { continue }
            $t = $p.ToUpperInvariant()
            if ($seen.ContainsKey($t)) { continue }
            $seen[$t] = $true
            [void]$out.Add($t)
        }
    }
    return [string[]]($out.ToArray())
}

function Read-WatchlistTickerLines {
    param([string[]]$Lines)
    if (-not $Lines -or $Lines.Count -eq 0) { return @() }
    $out = New-Object System.Collections.Generic.List[string]
    foreach ($line in $Lines) {
        if ($null -eq $line) { continue }
        $t = ([string]$line).Trim()
        if ($t.Length -eq 0) { continue }
        if ($t.StartsWith('#')) { continue }
        $hash = $t.IndexOf('#')
        if ($hash -ge 0) { $t = $t.Substring(0, $hash).Trim() }
        if ($t.Length -eq 0) { continue }
        foreach ($piece in ($t -split '[,\s;]+', [StringSplitOptions]::RemoveEmptyEntries)) {
            $p = $piece.Trim()
            if ($p.Length -eq 0) { continue }
            [void]$out.Add($p.ToUpperInvariant())
        }
    }
    return [string[]]($out.ToArray())
}

Set-Location $RepoRoot

if (-not (Test-Path $AwkScript)) {
    Write-Host "AWK script not found: $AwkScript" -ForegroundColor Red
    exit 1
}

$dataPath = Join-Path $RepoRoot "data\newdata\data"
$dataPattern = Split-Path $DataGlob -Leaf
$symListExpanded = @(Expand-TickerSymbols $Symbols)
$defaultWatchPath = Join-Path $RepoRoot "data\watchlist.txt"
$watchPaths = @()
if ($WatchlistFile -and (Test-Path -LiteralPath $WatchlistFile)) {
    $watchPaths += $WatchlistFile
}
elseif ($WatchlistFile) {
    Write-Warning "Watchlist file not found (skipping): $WatchlistFile"
}
# Optional repo file: only auto-merge with an explicit -s filter (never restrict full-universe runs).
if ($Symbols.Count -gt 0 -and (Test-Path -LiteralPath $defaultWatchPath)) {
    $watchPaths += $defaultWatchPath
}
$watchSyms = @()
foreach ($wp in ($watchPaths | Select-Object -Unique)) {
    $watchSyms += @(Read-WatchlistTickerLines (Get-Content -LiteralPath $wp -ErrorAction SilentlyContinue))
}
if ($watchSyms.Count -gt 0) {
    $symListExpanded = @(Expand-TickerSymbols ($symListExpanded + $watchSyms))
    Write-Host "  Watchlist merge: $($watchSyms.Count) ticker line(s) from $($watchPaths.Count) file(s) -> $($symListExpanded.Count) unique symbol(s) in filter." -ForegroundColor DarkGray
}
$useSymbolFilter = $symListExpanded.Count -gt 0
$symbolsCsvForPython = ($symListExpanded -join ',')
$awkInputPaths = New-Object System.Collections.Generic.List[string]

if ($useSymbolFilter) {
    $spyCsv = Join-Path $dataPath "SPY.csv"
    if (-not (Test-Path $spyCsv)) {
        Write-Host "SPY.csv required at $spyCsv" -ForegroundColor Red
        exit 1
    }
    [void]$awkInputPaths.Add($spyCsv)
    $seen = @{}
    $syms = $symListExpanded
    foreach ($sym in $syms) {
        if ($sym -eq "SPY") { continue }
        if ($seen.ContainsKey($sym)) { continue }
        $seen[$sym] = $true
        $one = Join-Path $dataPath "$sym.csv"
        if (-not (Test-Path $one)) {
            Write-Warning "Missing CSV for $sym (skipping): $one"
            continue
        }
        [void]$awkInputPaths.Add($one)
    }
    if ($awkInputPaths.Count -le 1) {
        Write-Host "No ticker CSVs matched -s (need at least one symbol with $sym.csv under $dataPath, besides SPY)." -ForegroundColor Red
        exit 1
    }
    $tickerCount = $awkInputPaths.Count - 1
} else {
    $tickerFiles = @(Get-ChildItem -Path $dataPath -Filter $dataPattern -ErrorAction SilentlyContinue)
    $tickerCount = $tickerFiles.Count
    $spyFull = Join-Path $RepoRoot ($SpyFile -replace '/', '\')
    [void]$awkInputPaths.Add($spyFull)
    foreach ($f in ($tickerFiles | Sort-Object Name)) {
        [void]$awkInputPaths.Add($f.FullName)
    }
}

Write-Host "Running portfolio audit..." -ForegroundColor Cyan
Write-Host "  Script: $AwkScript" -ForegroundColor Gray
Write-Host "  Data path: $dataPath" -ForegroundColor Gray
if ($useSymbolFilter) {
    Write-Host "  Symbol filter (-s): $tickerCount tickers (+ SPY)" -ForegroundColor Gray
} else {
    Write-Host "  Ticker files (PowerShell): $tickerCount" -ForegroundColor $(if ($tickerCount -lt 10) { 'Yellow' } else { 'Gray' })
    if ($tickerCount -lt 10) {
        Write-Host "  WARNING: Few ticker files found; audit may produce no closed trades. Check path and run from repo root." -ForegroundColor Yellow
    }
}
Write-Host ""

$lookCsv = Join-Path $RepoRoot "look.csv"
$diagTail = Join-Path $DriveDir "diagnostic_audit.txt"
$instTail = Join-Path $DriveDir "instrument.txt"

# Start time (always visible on console; AWK CON can be lost when stdout is redirected)
Write-Host "------------------------------------------------------------"
Write-Host ("AWK AUDIT START: " + (Get-Date -Format "HH:mm:ss"))
Write-Host "------------------------------------------------------------"
Write-Host "  Note: portfolio_audit.awk writes almost everything under drive\ (not stdout). look.csv" -ForegroundColor DarkGray
Write-Host "        may stay empty (gawk stdout/stderr only). diagnostic_audit.txt stays 0 bytes until END" -ForegroundColor DarkGray
Write-Host "        (DIAG_FILE is buffered); use troubleshoot_purchases.txt after the run for entry-filter counts." -ForegroundColor DarkGray
Write-Host "        For a live tail when debugging, prefer -Instrument (instrument.txt) or a small -s symbol set." -ForegroundColor DarkGray
Write-Host "        (diagnostic_audit.txt is only complete after the AWK run ends - it is not tailable mid-run.)" -ForegroundColor DarkGray
Write-Host "        look.csv only captures gawk stdout/stderr (e.g. DrawdownCalc). -Instrument writes $instTail" -ForegroundColor DarkGray
Write-Host "  Optional: -NoHeartbeat turns off 45s progress pings." -ForegroundColor DarkGray
Write-Host ""
$auditStart = Get-Date

# Invoke gawk directly (no cmd.exe): paths under "Program Files" contain spaces; cmd /c breaks them.
$awkExe = $null
foreach ($cand in @('C:\Program Files\Git\usr\bin\gawk.exe', 'C:\Program Files\Git\usr\bin\gawk')) {
    if (Test-Path -LiteralPath $cand) { $awkExe = $cand; break }
}
if (-not $awkExe) {
    $gw = Get-Command gawk -ErrorAction SilentlyContinue
    if ($gw) { $awkExe = $gw.Source }
}
if (-not $awkExe) {
    Write-Host "gawk not found (install Git for Windows or add gawk to PATH)." -ForegroundColor Red
    exit 1
}

# Windows CreateProcess command line is ~8191 chars; 1000+ full paths exceeds it ("filename too long").
# Pass a manifest file instead; portfolio_audit.awk reads RL_INPUT_MANIFEST in BEGIN and fills ARGV.
$manifestThresholdChars = 7000
$pathChars = 0
foreach ($p in $awkInputPaths) {
    $pathChars += $p.Length + 1
}
$useInputManifest = ($pathChars -ge $manifestThresholdChars)
$manifestPath = $null
if ($useInputManifest) {
    if (-not (Test-Path -LiteralPath $DriveDir)) {
        New-Item -ItemType Directory -Path $DriveDir -Force | Out-Null
    }
    $manifestPath = Join-Path $DriveDir "run_audit_input_manifest.txt"
    $manifestLines = foreach ($p in $awkInputPaths) { ConvertTo-UnixPath $p }
    $utf8NoBom = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllLines($manifestPath, [string[]]$manifestLines, $utf8NoBom)
    $manifestMsg = "  Input manifest (Windows command-line limit): {0} ({1} paths; would have been ~{2} chars as argv - manifest avoids that)." -f $manifestPath, $awkInputPaths.Count, $pathChars
    Write-Host $manifestMsg -ForegroundColor DarkYellow
}

$awkArgList = [System.Collections.Generic.List[string]]::new()
[void]$awkArgList.Add('-v'); [void]$awkArgList.Add('SMA_QUAL=1')
if ($RLTrailProfit -ne "") { [void]$awkArgList.Add('-v'); [void]$awkArgList.Add("RL_TRAIL_PROFIT=$RLTrailProfit") }
if ($RLTrailStop -ne "") { [void]$awkArgList.Add('-v'); [void]$awkArgList.Add("RL_TRAIL_STOP=$RLTrailStop") }
if ($RLTrailProfit2 -ne "") { [void]$awkArgList.Add('-v'); [void]$awkArgList.Add("RL_TRAIL_PROFIT2=$RLTrailProfit2") }
if ($RLTrailStop2 -ne "") { [void]$awkArgList.Add('-v'); [void]$awkArgList.Add("RL_TRAIL_STOP2=$RLTrailStop2") }
if ($Instrument) { [void]$awkArgList.Add('-v'); [void]$awkArgList.Add('INSTRUMENT=1') }
if ($SkipTrim) { [void]$awkArgList.Add('-v'); [void]$awkArgList.Add('SKIP_TRIM=1') }
if ($useInputManifest) {
    $mfUnix = ConvertTo-UnixPath $manifestPath
    [void]$awkArgList.Add('-v'); [void]$awkArgList.Add("RL_INPUT_MANIFEST=$mfUnix")
}
[void]$awkArgList.Add('-f'); [void]$awkArgList.Add($AwkScript)
if (-not $useInputManifest) {
    foreach ($p in $awkInputPaths) {
        [void]$awkArgList.Add($p)
    }
}

$awkExit = 0
$lookErrTmp = Join-Path $RepoRoot "look.stderr.tmp"
try {
    Set-Location $RepoRoot
    Remove-Item -LiteralPath $lookErrTmp -Force -ErrorAction SilentlyContinue
    Write-Host ""
    Write-Host "  gawk is starting (console stays quiet on purpose). Full universe ~1000+ tickers often takes many minutes." -ForegroundColor Green
    Write-Host '  Progress: wait ~45s for [audit] still running... or use -Instrument (disable heartbeat with -NoHeartbeat).' -ForegroundColor Green
    Write-Host ""
    # Start-Process avoids PowerShell re-parsing native stderr (e.g. Python from DrawdownCalc) as errors.
    # Heartbeat uses Wait-Process -Timeout (not Process.WaitForExit polling) so ExitCode is populated on exit.
    $awkProc = Start-Process -FilePath $awkExe -ArgumentList @($awkArgList.ToArray()) -WorkingDirectory $RepoRoot `
        -NoNewWindow -PassThru -RedirectStandardOutput $lookCsv -RedirectStandardError $lookErrTmp
    if ($null -eq $awkProc) {
        Write-Host "Start-Process failed to launch gawk." -ForegroundColor Red
        $awkExit = -1
    }
    elseif (-not $NoHeartbeat) {
        # Do not use Process.WaitForExit(ms) in a polling loop: on some Windows/.NET builds the ExitCode
        # property never gets populated after exit, so run_audit falsely reports exit -1. Wait-Process -Timeout
        # preserves ExitCode when the process eventually finishes.
        while (-not $awkProc.HasExited) {
            try {
                Wait-Process -InputObject $awkProc -Timeout 45 -ErrorAction Stop
                break
            }
            catch {
                $szL = 0
                if (Test-Path -LiteralPath $lookCsv) { $szL = (Get-Item -LiteralPath $lookCsv).Length }
                $szD = 0
                if (Test-Path -LiteralPath $diagTail) { $szD = (Get-Item -LiteralPath $diagTail).Length }
                Write-Host ("[audit] still running... diagnostic_audit.txt {0:n0} bytes | look.csv {1:n0} bytes" -f $szD, $szL) -ForegroundColor DarkCyan
            }
        }
        $awkExit = if ($null -ne $awkProc.ExitCode) { $awkProc.ExitCode } else { -1 }
    }
    else {
        Wait-Process -InputObject $awkProc
        $awkExit = if ($null -ne $awkProc.ExitCode) { $awkProc.ExitCode } else { -1 }
    }
    if (Test-Path -LiteralPath $lookErrTmp) {
        Get-Content -LiteralPath $lookErrTmp -Raw -ErrorAction SilentlyContinue | Add-Content -LiteralPath $lookCsv -Encoding utf8
        Remove-Item -LiteralPath $lookErrTmp -Force -ErrorAction SilentlyContinue
    }
} finally {
    Remove-Item -LiteralPath $lookErrTmp -Force -ErrorAction SilentlyContinue
}

# End time and duration (so you always see it on console)
$auditEnd = Get-Date
$durationSec = [math]::Round(($auditEnd - $auditStart).TotalSeconds, 1)
Write-Host ""
Write-Host "------------------------------------------------------------"
Write-Host ("AWK AUDIT END:   " + $auditEnd.ToString("HH:mm:ss") + " (duration: $durationSec s)")
Write-Host "------------------------------------------------------------"

if ($awkExit -ne 0) {
    Write-Host "Audit failed (exit code $awkExit). See look.csv for full output and errors." -ForegroundColor Red
    exit $awkExit
}

Write-Host ""
Write-Host "Audit completed successfully." -ForegroundColor Green
Write-Host ""

# Python for rl_emit_brt_mirror (see docs in .DESCRIPTION).
# Microsoft places BOTH (a) broken Store *stubs* python.exe / python3.exe and (b) the working
# Python Launcher py.exe under ...\Microsoft\WindowsApps\. A blanket "reject WindowsApps" breaks
# the normal working `py -3` path and is wrong. We only reject the stub filenames in that folder.
function Test-AuditPythonPath {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) { return $false }
    $lower = $Path.ToLowerInvariant()
    $inWinApps = ($lower -match '\\windowsapps\\' -or $lower -match '\\microsoft\\windowsapps\\')
    $leaf = [System.IO.Path]::GetFileName($Path).ToLowerInvariant()
    # App-execution-alias stubs (not runnable): deny.
    if ($inWinApps -and ($leaf -eq 'python.exe' -or $leaf -eq 'python3.exe' -or $leaf -eq 'pythonw.exe')) {
        return $false
    }
    # Store / WindowsApps: versioned python3.12.exe is the real runtime; Test-Path can be false on reparse.
    if ($inWinApps -and ($leaf -match '^python3\.\d+\.exe$')) {
        return $true
    }
    return (Test-Path -LiteralPath $Path)
}
function Get-FirstUsablePythonFromWhere {
    param([string]$CommandName)
    $list = @()
    $prevEa = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $raw = & where.exe $CommandName 2>$null
        if ($raw) { $list = @($raw) }
    } catch { }
    finally {
        $ErrorActionPreference = $prevEa
    }
    foreach ($line in $list) {
        $p = [string]$line.Trim().Trim('"')
        if (Test-AuditPythonPath $p) { return $p }
    }
    return $null
}

# Paths not on PATH (e.g. minimal env): Windows py launcher -0p, PEP 514 registry, python.org folders.
function Get-MirrorPythonCandidateExes {
    $candidates = @()

    $prevEa = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'

    $systemPy = Join-Path ([Environment]::GetFolderPath([Environment+SpecialFolder]::Windows)) 'py.exe'
    if (Test-Path -LiteralPath $systemPy) {
        try {
            $listOut = & $systemPy -0p 2>$null
            foreach ($line in @($listOut)) {
                $t = [string]$line.Trim()
                if (-not $t) { continue }
                $parts = $t -split '\s+'
                if ($parts.Count -lt 1) { continue }
                $exe = $parts[$parts.Count - 1].Trim('"')
                if ($exe -like '*.exe' -and (Test-Path -LiteralPath $exe)) {
                    $candidates += $exe
                }
            }
        } catch { }
    }

    foreach ($root in @('HKLM:\SOFTWARE\Python\PythonCore', 'HKCU:\SOFTWARE\Python\PythonCore', 'HKLM:\SOFTWARE\WOW6432Node\Python\PythonCore')) {
        if (-not (Test-Path -LiteralPath $root)) { continue }
        foreach ($kid in @(Get-ChildItem -LiteralPath $root -ErrorAction SilentlyContinue)) {
            $installPathKey = Join-Path $kid.PSPath 'InstallPath'
            if (-not (Test-Path -LiteralPath $installPathKey)) { continue }
            $dir = (Get-ItemProperty -LiteralPath $installPathKey -Name '(default)' -ErrorAction SilentlyContinue).'(default)'
            if ($dir -and (Test-Path -LiteralPath $dir)) {
                $exe = Join-Path $dir 'python.exe'
                if (Test-Path -LiteralPath $exe) { $candidates += $exe }
            }
        }
    }

    # Microsoft Store: stub is python3.exe; real interpreter is often python3.10.exe under PythonSoftwareFoundation.*\
    $winAppsUser = Join-Path $env:LOCALAPPDATA 'Microsoft\WindowsApps'
    if (Test-Path -LiteralPath $winAppsUser) {
        foreach ($f in @(Get-ChildItem -LiteralPath $winAppsUser -Filter 'python3*.exe' -File -ErrorAction SilentlyContinue)) {
            $leaf = $f.Name.ToLowerInvariant()
            if ($leaf -eq 'python3.exe') { continue }
            $candidates += $f.FullName
        }
    }

    # Common conda / manual layouts (PATH not always set for non-interactive shells)
    foreach ($rel in @(
            'miniconda3\python.exe', 'miniconda3\envs\base\python.exe',
            'Anaconda3\python.exe', 'anaconda3\python.exe',
            'mambaforge\python.exe', 'Miniforge3\python.exe'
        )) {
        $exe = Join-Path $env:USERPROFILE $rel
        if (Test-Path -LiteralPath $exe) { $candidates += $exe }
    }

    $pyRoots = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python'),
        (Join-Path $env:ProgramFiles 'Python')
    )
    $pf86 = [Environment]::GetFolderPath([Environment+SpecialFolder]::ProgramFilesX86)
    if ($pf86) { $pyRoots += (Join-Path $pf86 'Python') }
    foreach ($root in $pyRoots) {
        if (-not (Test-Path -LiteralPath $root)) { continue }
        Get-ChildItem -Path (Join-Path $root 'Python*') -Directory -ErrorAction SilentlyContinue | ForEach-Object {
            $exe = Join-Path $_.FullName 'python.exe'
            if (Test-Path -LiteralPath $exe) { $candidates += $exe }
        }
    }

    $ErrorActionPreference = $prevEa
    return ($candidates | Select-Object -Unique)
}

$MirrorPythonExe = $null
$MirrorPythonArgs = @()
if ($env:PYTHON_EXE -and (Test-AuditPythonPath $env:PYTHON_EXE)) {
    $MirrorPythonExe = $env:PYTHON_EXE
} elseif ($env:PYTHON -and (Test-AuditPythonPath $env:PYTHON)) {
    $MirrorPythonExe = $env:PYTHON
} else {
    $p = Get-FirstUsablePythonFromWhere 'py'
    if ($p) {
        $MirrorPythonExe = $p
        if ($p -match '[\\/]py\.exe$') { $MirrorPythonArgs = @('-3') }
    }
    if (-not $MirrorPythonExe) {
        $p = Get-FirstUsablePythonFromWhere 'python3'
        if ($p) { $MirrorPythonExe = $p }
    }
    if (-not $MirrorPythonExe) {
        $p = Get-FirstUsablePythonFromWhere 'python'
        if ($p) { $MirrorPythonExe = $p }
    }
    if (-not $MirrorPythonExe) {
        foreach ($name in @('py', 'python3', 'python')) {
            foreach ($c in @(Get-Command $name -All -ErrorAction SilentlyContinue)) {
                if (-not $c.Source) { continue }
                if (Test-AuditPythonPath $c.Source) {
                    $MirrorPythonExe = $c.Source
                    if ($c.Source -match '[\\/]py\.exe$') { $MirrorPythonArgs = @('-3') }
                    break 2
                }
            }
        }
    }
    # Last resort: unqualified `py -3` (same as typing in a shell — avoids resolving to python3.exe stub).
    if (-not $MirrorPythonExe -and (Get-Command py -ErrorAction SilentlyContinue)) {
        $MirrorPythonExe = 'py'
        $MirrorPythonArgs = @('-3')
    }
}

if (-not $MirrorPythonExe) {
    foreach ($cand in @(Get-MirrorPythonCandidateExes)) {
        if (Test-AuditPythonPath $cand) {
            $MirrorPythonExe = $cand
            $MirrorPythonArgs = @()
            break
        }
    }
}

if (-not $MirrorPythonExe) {
    Write-Host "No Python found for the BRT mirror step." -ForegroundColor Red
    Write-Host "Set PYTHON_EXE to your python.exe, or install Python from python.org (include py launcher)." -ForegroundColor Red
    $winDir = [Environment]::GetFolderPath([Environment+SpecialFolder]::Windows)
    $wp = Join-Path $winDir 'py.exe'
    $pyAll = @(Get-Command python -All -ErrorAction SilentlyContinue | ForEach-Object { $_.Source })
    $wherePy = @()
    $prevEa = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { $wherePy = @(& where.exe python 2>$null) } catch { }
    finally { $ErrorActionPreference = $prevEa }
    $candN = @()
    try { $candN = @(Get-MirrorPythonCandidateExes) } catch { $candN = @('(Get-MirrorPythonCandidateExes failed)') }
    Write-Host "Diagnostics: Windows py.exe=$([bool](Test-Path -LiteralPath $wp)); Get-Command py=$(if (Get-Command py -ErrorAction SilentlyContinue) { 'yes' } else { 'no' })" -ForegroundColor DarkGray
    Write-Host "  Get-Command python -All ($($pyAll.Count)): $($pyAll -join ' | ')" -ForegroundColor DarkGray
    Write-Host "  where.exe python ($($wherePy.Count)): $($wherePy -join ' | ')" -ForegroundColor DarkGray
    Write-Host "  expanded candidates ($($candN.Count)): $($candN -join ' | ')" -ForegroundColor DarkGray
    exit 1
}
Write-Host "BRT mirror Python: $MirrorPythonExe$(if ($MirrorPythonArgs.Count) { ' ' + ($MirrorPythonArgs -join ' ') })" -ForegroundColor DarkGray

# Emit BRT-shaped CSVs from RL outputs (BRT_Closed_RL_*, BRT_Open_RL_*, BRT_Audit_Report_RL_*).
$MirrorScript = Join-Path $RepoRoot "stock_analysis\rl_emit_brt_mirror.py"
$MirrorDataDir = Join-Path $RepoRoot "data\newdata\data"
if (Test-Path $MirrorScript) {
    Write-Host "Emitting BRT mirror from Rocket Launcher outputs..." -ForegroundColor Cyan
    if ($useSymbolFilter) {
        & $MirrorPythonExe @MirrorPythonArgs $MirrorScript --output-dir $DriveDir --data-dir $MirrorDataDir --symbols $symbolsCsvForPython
    } else {
        & $MirrorPythonExe @MirrorPythonArgs $MirrorScript --output-dir $DriveDir --data-dir $MirrorDataDir
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Host "rl_emit_brt_mirror.py failed (exit $LASTEXITCODE)." -ForegroundColor Red
        exit $LASTEXITCODE
    }
    Write-Host "BRT mirror CSVs written under $DriveDir" -ForegroundColor Green
    Write-Host ""
} else {
    Write-Host "Skip BRT mirror: $MirrorScript not found." -ForegroundColor Yellow
    Write-Host ""
}

if ($SkipRegressionCheck) {
    Write-Host "Regression check skipped (SkipRegressionCheck)." -ForegroundColor Gray
    exit 0
}

if (-not (Test-Path $RegressionScript)) {
    Write-Host "RegressionCheck.ps1 not found at $RegressionScript. Skipping regression check." -ForegroundColor Yellow
    exit 0
}

$regressParams = @{
    OutputDir        = $DriveDir
    FailOnRegression = -not $AllowRegression
}
& $RegressionScript @regressParams
exit $LASTEXITCODE
