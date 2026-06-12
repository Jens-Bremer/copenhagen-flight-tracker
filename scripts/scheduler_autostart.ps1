#Requires -RunAsAdministrator
#Requires -Version 5.1
#
# Configure Windows Task Scheduler to auto-start the flight tracker scheduler.
# This script must be run as Administrator.
#
# Usage:
#   .\scripts\scheduler_autostart.ps1
#
# This creates a scheduled task that:
# - Runs when the system starts (before any user logs in)
# - Launches the Python scheduler daemon
# - Restarts automatically if the process crashes
#
$ErrorActionPreference = 'Stop'
$WarningPreference = 'SilentlyContinue'

# Get the repo root (parent of scripts directory)
$RepoRoot = Split-Path -Parent $PSScriptRoot
$ScriptPath = Join-Path $RepoRoot 'scripts' 'run_scheduler.py'
$WrapperPath = Join-Path $RepoRoot 'scripts' 'run_scheduler_logged.ps1'

if (-not (Test-Path $ScriptPath)) {
    Write-Host "ERROR: run_scheduler.py not found at $ScriptPath"
    exit 1
}
if (-not (Test-Path $WrapperPath)) {
    Write-Host "ERROR: run_scheduler_logged.ps1 not found at $WrapperPath"
    exit 1
}

# Task name and description
$TaskName = 'FlightTrackerScheduler'
$TaskDescription = 'Copenhagen flight tracker daemon — runs price scraping collection.'

# Check if task already exists
$ExistingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($ExistingTask) {
    Write-Host "Task '$TaskName' already exists. Unregistering old task..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# Run PowerShell to invoke the logging wrapper, so stdout+stderr are captured to logs\scheduler.out.log.
$PwshExe = (Get-Command powershell.exe -ErrorAction SilentlyContinue)?.Source
if (-not $PwshExe) { $PwshExe = 'powershell.exe' }

Write-Host "Using PowerShell: $PwshExe"
Write-Host "Wrapper script: $WrapperPath"
Write-Host "Repo root: $RepoRoot"

# Create a scheduled task to run at system startup
$Principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType 'ServiceAccount' -RunLevel 'Highest'

# Run at system startup (task trigger)
$Trigger = New-ScheduledTaskTrigger -AtStartup

# Action: run PowerShell wrapper so stdout+stderr land in logs\scheduler.out.log
$Action = New-ScheduledTaskAction `
    -Execute $PwshExe `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$WrapperPath`"" `
    -WorkingDirectory $RepoRoot

# Task settings: restart on failure, allow on-demand execution, etc.
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
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
    Write-Host "  - Runs at system startup (before user login)"
    Write-Host "  - Runs with SYSTEM privileges (highest level)"
    Write-Host "  - Automatically restarts if the process crashes"
    Write-Host "  - Runs in working directory: $RepoRoot"
    Write-Host ""
    Write-Host "To verify the task:"
    Write-Host "  taskschd.msc"
    Write-Host ""
    Write-Host "To start the task immediately (for testing):"
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
