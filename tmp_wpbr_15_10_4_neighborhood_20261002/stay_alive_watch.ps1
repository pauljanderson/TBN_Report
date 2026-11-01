$ErrorActionPreference = "Continue"
$Root = "C:\Users\songg\Downloads\stockresearch"
$Tmp = Join-Path $Root "tmp_wpbr_15_10_4_neighborhood_20261002"
$Stamp = Join-Path $Root "drive\paul_experiments\wpbr_15_10_4_neighborhood_20261002"
$Log = Join-Path $Tmp "stay_alive_watch.log"
$Prog = Join-Path $Tmp "progress.txt"
$CapPath = Join-Path $Tmp "concurrency_cap.txt"
$Py = "C:\Users\songg\AppData\Local\Programs\Python\Python310\python.exe"
$Sup = Join-Path $Root "tools\wpbr_15_10_4_neighborhood_20261002.py"
$SupLog = Join-Path $Tmp "supervisor_cap2_nocpugate.log"
$DesiredCap = 4
function Write-Log($m) { $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $m; Add-Content -Path $Log -Value $line -Encoding UTF8 }
function Get-SupervisorPid {
  $procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -and $_.CommandLine -match 'wpbr_15_10_4_neighborhood_20261002\.py' -and $_.CommandLine -notmatch 'spawn_main' }
  if ($procs) { return @($procs)[0].ProcessId }
  return 0
}
function Get-EngineCount {
  @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -and $_.CommandLine -match 'rocket_tbn\.py' -and $_.CommandLine -match 'tmp_wpbr_15_10_4_neighborhood_20261002' -and $_.CommandLine -notmatch 'spawn_main|multiprocessing' }).Count
}
function Get-Scored {
  if (-not (Test-Path (Join-Path $Stamp "summary.csv"))) { return 0 }
  $csv = Import-Csv (Join-Path $Stamp "summary.csv")
  @($csv | Where-Object { $_.arm_id -ne 'control' -and $_.slice -eq 'FULL' } | Select-Object -ExpandProperty arm_id -Unique).Count
}
function Ensure-Cap {
  try {
    $cur = ""
    if (Test-Path $CapPath) { $cur = (Get-Content $CapPath -ErrorAction SilentlyContinue | Select-Object -First 1).Trim() }
    if ($cur -ne "$DesiredCap") {
      [System.IO.File]::WriteAllText($CapPath, "$DesiredCap`n")
      Write-Log "enforced concurrency_cap=$DesiredCap (was '$cur')"
    }
  } catch {
    Write-Log "cap_enforce_error $($_.Exception.Message)"
  }
}
Write-Log "watch_start pid=$PID durable stay_alive desired_cap=$DesiredCap"
Ensure-Cap
while ($true) {
  try {
    Ensure-Cap
    $scored = Get-Scored
    $eng = Get-EngineCount
    $sup = Get-SupervisorPid
    $cpu = try { (Get-CimInstance Win32_Processor | Measure-Object LoadPercentage -Average).Average } catch { -1 }
    $html = Test-Path (Join-Path $Stamp "compare.html")
    "scored_cells=$scored`ncap=$DesiredCap`nengines=$eng`nsupervisor=$sup`ncpu=$cpu`nhtml=$html`n" | Set-Content -Path $Prog -Encoding UTF8
    Write-Log "scored=$scored/125 engines=$eng supervisor=$sup cpu=$cpu html=$html cap=$DesiredCap"
    if ($scored -ge 125 -and $html) { Write-Log "COMPLETE 125/125 html present; watch exit"; break }
    if ($sup -eq 0) {
      Write-Log "supervisor missing; restarting into $SupLog"
      $psi = New-Object System.Diagnostics.ProcessStartInfo
      $psi.FileName = $Py
      $psi.Arguments = "-u `"$Sup`""
      $psi.WorkingDirectory = $Root
      $psi.UseShellExecute = $false
      $psi.RedirectStandardOutput = $true
      $psi.RedirectStandardError = $true
      $psi.CreateNoWindow = $true
      $p = New-Object System.Diagnostics.Process
      $p.StartInfo = $psi
      [void]$p.Start()
      Start-Job -ScriptBlock { param($proc,$log) while (-not $proc.HasExited) { $o=$proc.StandardOutput.ReadLine(); if ($null -ne $o) { Add-Content $log $o } } } -ArgumentList $p,$SupLog | Out-Null
      Write-Log "restarted supervisor pid=$($p.Id)"
    }
  } catch {
    Write-Log "watch_error $($_.Exception.Message)"
  }
  Start-Sleep -Seconds 60
}
