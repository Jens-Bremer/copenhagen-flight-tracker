# scripts/

Quick reference for every script in this directory.

| Script | Description | Run it |
|--------|-------------|--------|
| `run_scheduler.py` | Continuous daemon — orchestrates daily collection, backups, health checks, CSV export, and frontend regeneration | `python scripts/run_scheduler.py` |
| `run_daily.py` | Single collection cycle — expand routes/dates, fetch, parse, insert, retry failures, alert on cheap flights | `python scripts/run_daily.py` |
| `run_health_check.py` | Standalone health check with ntfy alerting | `python scripts/run_health_check.py` |
| `setup_db.py` | Initialize the SQLite database (safe to re-run) | `python scripts/setup_db.py` |
| `backup_db.py` | Snapshot `data/flights.db` to `data/backups/`, prune old backups | `python scripts/backup_db.py` |
| `export_csv.py` | Export all observations to `data/flights_export.csv` | `python scripts/export_csv.py` |
| `build_frontend_csv.py` | Build slim frontend CSV at `data/flights_frontend.csv` | `python scripts/build_frontend_csv.py` |
| `generate_html.py` | Read frontend CSV and write `frontend/index.html` and `frontend/airlines.html` | `python scripts/generate_html.py` |
| `fetch_vendor.py` | Download Chart.js 4.4.3 into `frontend/vendor/` (one-time setup) | `python scripts/fetch_vendor.py` |
| `query_prices.py` | CLI data inspector: `--stats`, `--cheapest`, `--date YYYY-MM-DD` | `python scripts/query_prices.py --stats` |
| `collection.py` | Reusable fetch→parse→store unit — used by `run_daily.py` to execute single collection jobs | `python scripts/collection.py` |
| `regenerate_frontend.py` | Regenerate full frontend pipeline: export DB → slim CSV → HTML (runs build_frontend_csv.py + generate_html.py) | `python scripts/regenerate_frontend.py` |
| `backtest.py` | CLI utility for backtesting historical buy-day strategies against recorded flight prices | `python scripts/backtest.py --route CPH-AMS` |
| `build_frontend_csv.py` | Build slim analytics-ready CSV at `data/flights_frontend.csv` from flights_export.csv | `python scripts/build_frontend_csv.py` |

## Windows-only scripts (PowerShell Task Scheduler integration)

| Script | Description | Run it |
|--------|-------------|--------|
| `update.ps1` | Windows update wrapper: stops daemon, pulls latest code, reinstalls deps, restarts scheduler | `.\scripts\update.ps1` |
| `scheduler_autostart.ps1` | Register the scheduler daemon to auto-start at system boot via Windows Task Scheduler | `.\scripts\scheduler_autostart.ps1` |
| `health_check.ps1` | Run health check manually with ntfy alerting (Windows) | `.\scripts\health_check.ps1` |
| `health_check_task.ps1` | Register health check to run daily at 23:30 via Windows Task Scheduler | `.\scripts\health_check_task.ps1` |

## Linux-only scripts

| Script | Description | Run it |
|--------|-------------|--------|
| `update.sh` | Linux update wrapper: stops daemon, pulls latest code, reinstalls deps, validates config, restarts scheduler | `bash scripts/update.sh` |
