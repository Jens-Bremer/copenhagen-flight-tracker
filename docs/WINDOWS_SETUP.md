# Windows Setup Guide

This document describes how to set up the flight tracker daemon to run continuously on Windows with automatic startup and health checks.

## Prerequisites

- Windows 10/11 or Windows Server 2016+
- PowerShell 5.1+ (included with Windows 10/11)
- Administrator privileges
- Python 3.9+ installed
- Virtual environment set up (`pip install -e .`)
- Playwright browser installed (`playwright install chromium`)

## Initial Setup

### 1. Configure the Application

On first install, copy the config template:

```bash
# Windows (Command Prompt)
copy config.example.py config.py

# Or on Unix/macOS
cp config.example.py config.py
```

Then edit `config.py` and replace the placeholders:
- `NTFY_TOPIC`: change to a random unguessable string for notifications
- Any IP addresses or local values for your setup

### 2. Install Dependencies

```bash
pip install -e .
playwright install chromium
python scripts/setup_db.py
```

### 2. Validate Configuration

Ensure `config.py` is correctly configured before setting up automation:

```bash
python -c "from src.config_validator import validate_config; import config; validate_config(vars(config))"
```

## Automatic Startup on System Boot

### Setup

To configure the scheduler to start automatically when Windows boots:

```powershell
# Run PowerShell as Administrator
.\scripts\scheduler_autostart.ps1
```

This creates a Windows Task Scheduler entry that:
- Runs at system startup (before user login)
- Executes with SYSTEM privileges
- Automatically restarts if the process crashes
- Restarts up to 5 times with 1-minute intervals between restarts

### Verification

To verify the task was created:

```powershell
# View the task in Task Scheduler
taskschd.msc

# Or query via PowerShell
Get-ScheduledTask -TaskName 'FlightTrackerScheduler' | Get-ScheduledTaskInfo
```

### Testing

To run the task immediately (without waiting for a system restart):

```powershell
schtasks /run /tn 'FlightTrackerScheduler'
```

### Removal

To disable automatic startup:

```powershell
Unregister-ScheduledTask -TaskName 'FlightTrackerScheduler' -Confirm:$false
```

## Periodic Health Checks

### Setup

To configure the health check to run daily at 23:30:

```powershell
# Run PowerShell as Administrator
.\scripts\health_check_task.ps1
```

This creates a Windows Task Scheduler entry that:
- Runs every day at 23:30 (11:30 PM)
- Validates the database and scraper health
- Sends alerts via ntfy if problems are detected
- Executes with SYSTEM privileges

### Verification

```powershell
# View the task in Task Scheduler
taskschd.msc

# Or query via PowerShell
Get-ScheduledTask -TaskName 'FlightTrackerHealthCheck' | Get-ScheduledTaskInfo
```

### Testing

```powershell
schtasks /run /tn 'FlightTrackerHealthCheck'
```

### Removal

```powershell
Unregister-ScheduledTask -TaskName 'FlightTrackerHealthCheck' -Confirm:$false
```

## Updating

The scheduler automatically runs `update.ps1` at 23:55 each night — after the
collection window (06:00–22:00) and all nightly jobs. No manual timing needed.

`update.ps1` performs the following steps:
1. Stops the running scheduler (if any)
2. Pulls the latest code via git
3. Runs `pip install -e .` to update Python dependencies
4. Automatically runs `playwright install chromium` to keep the browser binary in sync with the installed package version
5. Validates the configuration
6. Updates the database schema (if needed)
7. Restarts the scheduler

This ensures that if Playwright is bumped in a dependency update, the Python package and the browser binary stay synchronized.

## Manual Operation

### Starting the Scheduler

```bash
python scripts/run_scheduler.py
```

The scheduler will:
1. Check for an existing PID file (prevents duplicate instances)
2. Initialize the database (migrations)
3. Install the browser automation patch
4. Wait until the configured daily window start time
5. Begin the daily collection cycle at regular intervals
6. Run nightly jobs (backup, health check, CSV export, HTML generation, auto-update)

### Running a Single Collection

To test or manually trigger a collection immediately:

```bash
python scripts/run_daily.py
```

### Querying Prices

```bash
python scripts/query_prices.py --stats
python scripts/query_prices.py --cheapest
python scripts/query_prices.py --date 2025-09-05
```

## Logs and Troubleshooting

### Log Files

When the scheduler is registered via `scripts\scheduler_autostart.ps1`, the
scheduled task invokes `scripts\run_scheduler_logged.ps1`, which appends both
stdout and stderr to `logs\scheduler.out.log` automatically. No manual
redirection is needed — silent task failures will leave a trace in that file.

If you run the scheduler interactively instead, output goes to the terminal:

```powershell
python scripts\run_scheduler.py
# or explicitly capture:
python scripts\run_scheduler.py *>> logs\scheduler.out.log
```

### Task Scheduler Logs

Windows Task Scheduler logs task execution in Event Viewer:
- Open `eventvwr.msc`
- Navigate to: Windows Logs → Application
- Filter by Event ID 101, 102, 103 (task scheduler events)

### Common Issues

**Task fails to start:**
- Verify virtual environment is set up: `.venv\Scripts\Activate.ps1`
- Verify Python path is correct in the task
- Run `python -c "import config"` to verify config is loadable

**No flights being scraped:**
- Check `NTFY_TOPIC` is set in `config.py`
- Check `ROUTES` list is populated with routes to track
- Verify `DAILY_WINDOW_START_HOUR` and `DAILY_WINDOW_END_HOUR` in config.py
- Check browser is installed: `playwright install chromium`

**Duplicate scrape runs:**
- Check the PID file isn't stale: `data\run_scheduler.pid`
- Remove the PID file if the scheduler crashed: `del data\run_scheduler.pid`

**Health check not running:**
- Verify the health check task exists: `schtasks /query /tn 'FlightTrackerHealthCheck'`
- Run manually to test: `schtasks /run /tn 'FlightTrackerHealthCheck'`
- Check ntfy topic is set: `NTFY_TOPIC` in `config.py`

## Uninstall

To completely remove the flight tracker:

```powershell
# Stop and remove scheduled tasks
Unregister-ScheduledTask -TaskName 'FlightTrackerScheduler' -Confirm:$false
Unregister-ScheduledTask -TaskName 'FlightTrackerHealthCheck' -Confirm:$false

# Remove the application directory
Remove-Item -Recurse -Force 'path\to\Copenhagen-flight-tracker'
```

## Additional Resources

- See `docs/DATA_RETENTION.md` for data retention policy
- See `CLAUDE.md` for architecture and design decisions
- Check `config.py` for all available configuration options
