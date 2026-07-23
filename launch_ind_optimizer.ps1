# Launch IND optimizer with ETA status file.
Set-Location $PSScriptRoot
New-Item -ItemType Directory -Force -Path logs | Out-Null
$py = Join-Path $env:LOCALAPPDATA "Programs\Python\Python310\python.exe"
if (-not (Test-Path $py)) {
    $py = (Get-Command python -ErrorAction Stop).Source
}
$ts = Get-Date -Format "yyMMddHHmmss"
$log = Join-Path (Get-Location) "logs\IND_Optimizer_$ts.log"
$err = Join-Path (Get-Location) "logs\IND_Optimizer_$ts.err.log"
$proc = Start-Process -FilePath $py `
    -ArgumentList @("-u", "stock_analysis\IND_Optimizer.py", "--reset", "-w", "1", "-b", "30") `
    -WorkingDirectory (Get-Location).Path `
    -RedirectStandardOutput $log `
    -RedirectStandardError $err `
    -WindowStyle Hidden `
    -PassThru
@(
    "PID=$($proc.Id)"
    "LOG=$log"
    "ERR=$err"
    "CMD=$py -u stock_analysis\IND_Optimizer.py --reset -w 1 -b 30"
    "STATUS=stock_analysis\IND_optimizer_status.txt"
) | Set-Content -Path "logs\IND_Optimizer_pid.txt"
Write-Output "STARTED_PID=$($proc.Id)"
Write-Output "LOG=$log"
Write-Output "ERR=$err"
Start-Sleep -Seconds 6
if (Test-Path $log) {
    Write-Output "--- LOG HEAD ---"
    Get-Content $log -TotalCount 30
}
if (Test-Path $err) {
    Write-Output "--- ERR HEAD ---"
    Get-Content $err -TotalCount 30
}
$statusPath = "stock_analysis\IND_optimizer_status.txt"
if (Test-Path $statusPath) {
    Write-Output "--- STATUS ---"
    Get-Content $statusPath
}
Write-Output "ALIVE=$(-not $proc.HasExited)"
