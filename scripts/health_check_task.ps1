#Requires -RunAsAdministrator
#Requires -Version 5.1
#
# Configure Windows Task Scheduler to run the health check periodically.
# This script must be run as Administrator.
#
# Usage:
#   .\scripts\health_check_task.ps1
#
# This creates a scheduled task that:
# - Runs the health check script at 23:30 every day
# - Alerts via ntfy if problems are detected
#
$ErrorActionPreference = 'Stop'
$WarningPreference = 'SilentlyContinue'

# Get the repo root (parent of scripts directory)
$RepoRoot = Split-Path -Parent $PSScriptRoot
$HealthCheckScript = Join-Path $RepoRoot 'scripts' 'health_check.ps1'

if (-not (Test-Path $HealthCheckScript)) {
    Write-Host "ERROR: health_check.ps1 not found at $HealthCheckScript"
    exit 1
}

# Task name and description
$TaskName = 'FlightTrackerHealthCheck'
$TaskDescription = 'Flight tracker health check — runs daily at 23:30.'

# Check if task already exists
$ExistingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($ExistingTask) {
    Write-Host "Task '$TaskName' already exists. Unregistering old task..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Write-Host "Script path: $HealthCheckScript"
Write-Host "Repo root: $RepoRoot"

# Create a scheduled task to run at 23:30 daily
$Principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType 'ServiceAccount' -RunLevel 'Highest'

# Trigger: every day at 23:30 (11:30 PM)
$Trigger = New-ScheduledTaskTrigger -Daily -At 23:30

# Action: run the health check PowerShell script
$Action = New-ScheduledTaskAction `
    -Execute 'powershell.exe' `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$HealthCheckScript`"" `
    -WorkingDirectory $RepoRoot

# Task settings
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew

# Register the task
try {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Description $TaskDescription `
        -Principal $Principal `
        -Trigger $Trigger `
        -Action $Action `
        -Settings $Settings `
        -Force | Out-Null

    Write-Host "Successfully created scheduled task '$TaskName'"
    Write-Host ""
    Write-Host "Task Details:"
    Write-Host "  - Runs daily at 23:30 (11:30 PM)"
    Write-Host "  - Runs with SYSTEM privileges (highest level)"
    Write-Host "  - Alerts via ntfy if problems detected"
    Write-Host "  - Working directory: $RepoRoot"
    Write-Host ""
    Write-Host "To verify the task:"
    Write-Host "  taskschd.msc"
    Write-Host ""
    Write-Host "To run the task immediately (for testing):"
    Write-Host "  schtasks /run /tn '$TaskName'"
    Write-Host ""
    Write-Host "To view task logs:"
    Write-Host "  Get-ScheduledTaskInfo -TaskName '$TaskName'"
    Write-Host ""
}
catch {
    Write-Host "ERROR: Failed to create scheduled task: $_"
    exit 1
}
