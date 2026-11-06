#Requires -RunAsAdministrator
<#
.SYNOPSIS
  Point every \TBN* scheduled task WorkingDirectory at C:\Users\songg\code\TBN.

  2026-11-06: tasks ran TBN bats but Start-in was Downloads\stockresearch.
  Combined with a drive junction + old hardcoded DATA_DIR, the 10:50 update
  refreshed Downloads data while TBN data/ stayed on 11-04 bars.

  Run elevated once after the repo split:
    powershell -ExecutionPolicy Bypass -File tools\fix_tbn_task_scheduler_startin.ps1
#>
$ErrorActionPreference = "Stop"
$newWd = "C:\Users\songg\code\TBN"
$tasks = Get-ScheduledTask | Where-Object { $_.TaskName -match "TBN" }
if (-not $tasks) {
    Write-Host "No scheduled tasks matching TBN."
    exit 0
}
foreach ($t in $tasks) {
    $td = $t.Actions | Select-Object -First 1
    Write-Host "TASK $($t.TaskPath)$($t.TaskName)"
    Write-Host "  was StartIn=$($td.WorkingDirectory)"
    $params = @{ Execute = $td.Execute; WorkingDirectory = $newWd }
    if ($td.Arguments) { $params.Argument = $td.Arguments }
    $action = New-ScheduledTaskAction @params
    Set-ScheduledTask -TaskName $t.TaskName -TaskPath $t.TaskPath -Action $action | Out-Null
    $check = (Get-ScheduledTask -TaskName $t.TaskName -TaskPath $t.TaskPath).Actions | Select-Object -First 1
    Write-Host "  now StartIn=$($check.WorkingDirectory)"
}
Write-Host "Done."
