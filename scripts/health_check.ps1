#Requires -Version 5.1
#
# Run the health check and alert via ntfy if problems found.
# This script is designed to be called from Windows Task Scheduler.
#
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')

try {
    if (Test-Path .venv\Scripts\Activate.ps1) { . .venv\Scripts\Activate.ps1 }
    Write-Host "Running health check..."
    python scripts\run_health_check.py
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Health check passed."
    } else {
        Write-Host "Health check detected problems; alerts sent via ntfy."
    }
}
catch {
    Write-Host "Health check failed: $_"
    exit 1
}
