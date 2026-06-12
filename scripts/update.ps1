#Requires -Version 5.1
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')

$PidFile = 'data\run_scheduler.pid'

# When invoked manually, stop a running scheduler. When invoked from the 23:55
# auto-update job, the scheduler has already exited itself before spawning us,
# so the PID file points at a dead process — Get-Process returns a not-found
# error and we simply clean it up.
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
        Write-Host "Stale PID file (process $sched not running); cleaning up."
    }
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}
else {
    Write-Host "No scheduler PID file found; assuming not running."
}

# config.py is intentionally untracked (see config.example.py for the template).
# Use --autostash to safely handle any remaining tracked-file edits during rebase.

# Send a high-priority ntfy alert. Reads NTFY_TOPIC from config.py so we don't
# hard-code it. Best-effort — never aborts the update flow.
function Send-NtfyAlert {
    param([string]$Title, [string]$Body)
    try {
        $topic = (python -c "import config; print(config.NTFY_TOPIC)").Trim()
        if ([string]::IsNullOrWhiteSpace($topic)) { return }
        Invoke-RestMethod -Method Post -Uri "https://ntfy.sh/$topic" `
            -Headers @{ Title = $Title; Priority = "high" } `
            -Body $Body -TimeoutSec 10 | Out-Null
    }
    catch {
        Write-Host "ntfy alert send failed: $_"
    }
}

try {
    Write-Host "Pulling latest code..."
    git pull --rebase --autostash
    if ($LASTEXITCODE -ne 0) { throw "git pull --rebase --autostash failed" }

    if (Test-Path .venv\Scripts\Activate.ps1) { . .venv\Scripts\Activate.ps1 }
    pip install -e .
    if ($LASTEXITCODE -ne 0) { throw "pip install -e . failed" }

    # Only reinstall the Playwright browser when the package version changed.
    # Running the installer on every nightly update is slow and can silently
    # crash in a fully detached, consoleless Windows process.
    $playwrightVersion = (python -m playwright --version 2>&1).Trim()
    $versionMarker = "data\.playwright_version"
    if (-not (Test-Path $versionMarker) -or (Get-Content $versionMarker -Raw).Trim() -ne $playwrightVersion) {
        Write-Host "Playwright version changed to $playwrightVersion — installing chromium..."
        python -m playwright install chromium
        if ($LASTEXITCODE -ne 0) { throw "playwright install chromium failed" }
        Set-Content $versionMarker $playwrightVersion
    } else {
        Write-Host "Playwright chromium up to date ($playwrightVersion) — skipping install."
    }

    python -c "from src.config_validator import validate_config; import config; validate_config(vars(config))"
    if ($LASTEXITCODE -ne 0) { throw "config validation failed" }
    python scripts\setup_db.py
    if ($LASTEXITCODE -ne 0) { throw "setup_db.py failed" }
    Write-Host "Update successful."
}
catch {
    $err = "$_"
    Write-Host "Update failed: $err"
    Send-NtfyAlert -Title "Flight tracker: auto-update failed" -Body $err
}
finally {
    Write-Host "Restarting scheduler..."
    Start-Process -WindowStyle Hidden python -ArgumentList 'scripts\run_scheduler.py'
    Write-Host "Update complete - scheduler restarted."
}
