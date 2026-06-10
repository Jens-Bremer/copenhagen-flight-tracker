#Requires -Version 5.1
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')

$PidFile = 'data\run_scheduler.pid'
if (Test-Path $PidFile) {
    $sched = Get-Content $PidFile
    try {
        $proc = Get-Process -Id $sched -ErrorAction Stop
        Write-Host "Stopping scheduler (PID $sched)..."
        $proc | Stop-Process
        $proc | Wait-Process -Timeout 30
        Write-Host "Scheduler stopped."
    }
    catch [Microsoft.PowerShell.Commands.ProcessCommandException] {
        Write-Host "Stale PID file (process $sched not running); ignoring."
    }
}
else {
    Write-Host "No scheduler PID file found; assuming not running."
}

# Refuse update if working tree has uncommitted edits to tracked files.
git diff --quiet HEAD
if ($LASTEXITCODE -ne 0) {
    Write-Host "Refusing to update: uncommitted changes to tracked files."
    exit 1
}

try {
    Write-Host "Pulling latest code..."
    git pull --rebase

    if (Test-Path .venv\Scripts\Activate.ps1) { . .venv\Scripts\Activate.ps1 }
    pip install -e .

    python -c "from src.config_validator import validate_config; import config; validate_config(vars(config))"
    python scripts\setup_db.py
    Write-Host "Update successful."
}
catch {
    Write-Host "Update failed: $_"
}
finally {
    Write-Host "Restarting scheduler..."
    Start-Process -WindowStyle Hidden python -ArgumentList 'scripts\run_scheduler.py'
    Write-Host "Update complete — scheduler restarted."
}
