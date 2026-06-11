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

# config.py is intentionally untracked (see config.example.py for the template).
# Use --autostash to safely handle any remaining tracked-file edits during rebase.

try {
    Write-Host "Pulling latest code..."
    git pull --rebase --autostash

    if (Test-Path .venv\Scripts\Activate.ps1) { . .venv\Scripts\Activate.ps1 }
    pip install -e .

    # Keep the Playwright browser binary in sync with the installed Python package.
    Write-Host "Installing Playwright browser binaries..."
    python -m playwright install chromium
    if ($LASTEXITCODE -ne 0) {
        Write-Error "playwright install chromium failed"
        exit 1
    }

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
