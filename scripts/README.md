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
| `generate_html.py` | Read frontend CSV and write `frontend/index.html` | `python scripts/generate_html.py` |
| `fetch_vendor.py` | Download Chart.js 4.4.3 into `frontend/vendor/` (one-time setup) | `python scripts/fetch_vendor.py` |
| `query_prices.py` | CLI data inspector: `--stats`, `--cheapest`, `--date YYYY-MM-DD` | `python scripts/query_prices.py --stats` |
