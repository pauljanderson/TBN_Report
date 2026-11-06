<#
.SYNOPSIS
  Retarget Task Scheduler WorkingDirectory to C:\Users\songg\code\TBN.

  2026-11-06: tasks ran TBN bats but Start-in was Downloads\stockresearch.
  Combined with a drive junction + old hardcoded DATA_DIR, the 10:50 update
  refreshed Downloads data while TBN data/ stayed on 11-04 bars.

.PARAMETER Apply
  Actually change tasks. Default is list-only / -WhatIf style (no changes).

.EXAMPLE
  # List candidates only (default)
  powershell -ExecutionPolicy Bypass -File tools\fix_tbn_task_scheduler_startin.ps1

  # Apply (must be elevated for tasks that run whether user is logged on)
  powershell -ExecutionPolicy Bypass -File tools\fix_tbn_task_scheduler_startin.ps1 -Apply
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [switch]$Apply,
    [string]$NewWorkingDirectory = "C:\Users\songg\code\TBN"
)

$ErrorActionPreference = "Stop"

function Test-TbnRelatedAction {
    param($Action)
    $blob = @($Action.Execute, $Action.Arguments, $Action.WorkingDirectory) -join " "
    if ([string]::IsNullOrWhiteSpace($blob)) { return $false }
    return $blob -match '(?i)stockresearch|\\TBN\\|code\\TBN|TBN\\'
}

$tasks = @(Get-ScheduledTask | Where-Object {
    $nameHit = $_.TaskName -match '(?i)TBN'
    $actionHit = $false
    foreach ($a in @($_.Actions)) {
        if (Test-TbnRelatedAction $a) { $actionHit = $true; break }
    }
    $nameHit -or $actionHit
})

if (-not $tasks) {
    Write-Host "No scheduled tasks matching TBN / stockresearch paths."
    exit 0
}

$mode = if ($Apply) { "APPLY" } else { "LIST-ONLY (pass -Apply to change)" }
Write-Host "Mode: $mode"
Write-Host "Target WorkingDirectory: $NewWorkingDirectory"
Write-Host ""

foreach ($t in $tasks) {
    Write-Host "TASK $($t.TaskPath)$($t.TaskName)"
    $newActions = @()
    $changed = $false
    foreach ($a in @($t.Actions)) {
        $oldWd = [string]$a.WorkingDirectory
        $keep = Test-TbnRelatedAction $a
        if (-not $keep) {
            # Preserve unrelated actions on multi-action tasks unchanged.
            $params = @{ Execute = $a.Execute }
            if ($a.Arguments) { $params.Argument = $a.Arguments }
            if ($oldWd) { $params.WorkingDirectory = $oldWd }
            $newActions += New-ScheduledTaskAction @params
            Write-Host "  leave  Execute=$($a.Execute) StartIn=$oldWd"
            continue
        }
        $params = @{ Execute = $a.Execute; WorkingDirectory = $NewWorkingDirectory }
        if ($a.Arguments) { $params.Argument = $a.Arguments }
        $newActions += New-ScheduledTaskAction @params
        if ($oldWd -ne $NewWorkingDirectory) { $changed = $true }
        Write-Host "  was    Execute=$($a.Execute) StartIn=$oldWd"
        Write-Host "  ->     StartIn=$NewWorkingDirectory"
    }

    if (-not $Apply) {
        Write-Host "  (no change; list-only)"
        Write-Host ""
        continue
    }
    if (-not $changed) {
        Write-Host "  already correct"
        Write-Host ""
        continue
    }
    if ($PSCmdlet.ShouldProcess("$($t.TaskPath)$($t.TaskName)", "Set WorkingDirectory")) {
        try {
            Set-ScheduledTask -TaskName $t.TaskName -TaskPath $t.TaskPath -Action $newActions | Out-Null
            Write-Host "  UPDATED"
        } catch {
            Write-Host "  FAILED: $($_.Exception.Message)"
            Write-Host "  Re-run elevated if Access is denied."
        }
    }
    Write-Host ""
}

if (-not $Apply) {
    Write-Host "Dry run complete. Re-run with -Apply (elevated) to write changes."
}
