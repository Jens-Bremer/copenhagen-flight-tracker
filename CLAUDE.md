# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Philosophy & Current State

A self-hosted, extremely fault-tolerant Python service that tracks flight prices by scraping Google Flights via `fast-flights`. The core philosophy is **reliable passive data collection without IP bans** to eventually answer the question: *"When should I buy my ticket?"*

Currently, the project operates as a mature service with a full analytics frontend:
- **Scheduler-driven:** A single Python daemon (`run_scheduler.py`) manages its own daily pacing, health checks, backups, CSV exports, and frontend regeneration. No OS-level cron is required.
- **Fault-tolerant:** Transient network errors or single-flight failures do not crash the daily scrape. A two-pass retry system handles transient failures.
- **Strictly configured:** All settings live in `config.py`. All values are validated at startup before any work begins.

## Commands

```bash
# Install dependencies (production)
pip install -e .

# Install with dev extras (pytest, ruff)
pip install -e ".[dev]"

# Initialize the database (safe to run multiple times)
python scripts/setup_db.py

# Run the continuous daemon (orchestrates daily scrape + nightly jobs)
python scripts/run_scheduler.py

# Run a single collection immediately (useful for testing)
python scripts/run_daily.py

# Query stored data via CLI
python scripts/query_prices.py --stats
python scripts/query_prices.py --cheapest
python scripts/query_prices.py --date YYYY-MM-DD

# Generate frontend manually
python scripts/generate_html.py

# Run the complete test suite (333 tests)
pytest tests/
```

## Architecture & Workflow

### Orchestration
`scripts/run_scheduler.py` is the continuous daemon. It schedules five jobs:
1. **Daily collection** (06:00) — via `scripts/run_daily.py`: expands routes/dates, paces requests, fetches, parses, inserts, retries failures, alerts on cheap flights.
2. **Database backup** (01:00) — via `scripts/backup_db.py`: snapshots `data/flights.db`, prunes old backups.
3. **Health check** (23:30) — via `src/health_checker.py`: validates heartbeat, failure rates, observation counts, missing routes, price variance, currency consistency. Alerts via ntfy.
4. **CSV export** (23:45) — via `scripts/export_csv.py`: writes `data/flights_export.csv` for archival.
5. **Frontend CSV + HTML** (23:46) — via `src/frontend_csv_builder.py` then `src/html_generator.py`: builds `data/flights_frontend.csv`, then regenerates `frontend/index.html` inline.

### Data Flow
```
date_generator → route_expander → flight_fetcher → response_parser → database
                                       ↑                   ↑
                                   request_pacer        notifier/price_alerter
                                                              ↓
                                                        health_checker
                                                              ↓
                                                   analytics → html_generator → frontend/index.html
```

### Frontend Pipeline
The static dashboard is regenerated nightly with zero runtime fetches:
1. `src/frontend_csv_builder.py` reads the DB and writes `data/flights_frontend.csv` (slim, typed, sorted).
2. `src/html_generator.py` reads that CSV, computes analytics (`src/analytics.py`), and writes `frontend/index.html`.
3. Chart.js is vendored under `frontend/vendor/` and inlined into the HTML at build time.
4. The browser runs `frontend/app.js` (IIFE) against five embedded JSON blobs — no network requests needed.

### Module Contract
Each `src/` module imports only from `config` and stdlib/installed packages — **no cross-imports between `src/` modules** except for the analytics/HTML/CSV pipeline (`analytics.py`, `frontend_csv_builder.py`, `html_generator.py`, `price_alerter.py`) which form an allowed dependency chain. Every public function has type hints and a docstring. Pure functions stay in `src/`, while side effects (DB writes, HTTP calls, sleeps) are orchestrated in `scripts/`.

## Key Design Rules

1. **No hardcoded values:** All constants reference `config.X`.
2. **All config in `config.py`:** There is no `config_local.py` override mechanism. Edit `config.py` directly (it is tracked in git).
3. **Pacing & Jitter:** `request_pacer.py` adds ±10% jitter to evenly space requests across a daily window to look organic. `route_expander.py` shuffles jobs to avoid sequential identical routes.
4. **Logging everywhere:** The `logging` module is configured via `src/log_config.py`. Exception: `query_prices.py` uses plain `print` for CLI readability.
5. **Two-pass retry:** Failed jobs in the initial pass are retried sequentially with a configurable delay (`config.FETCH_RETRY_DELAY_SECONDS`).

## Database & Migrations

SQLite at `data/flights.db`.
- **Schema:** `flight_observations` table with an auto-increment `id` and a multi-column lookup index.
- **Rule for Updates:** **Never break historical data.** If adding features (e.g., Layovers, Round Trips), add new columns as `NULLABLE` so historical rows seamlessly parse, or create new tables entirely. Avoid renaming or deleting columns.

## Tests

The test suite relies heavily on `pytest` and `unittest.mock` (333 tests).
- **No real HTTP requests:** Always mock `fast-flights` API calls.
- **No real DB state:** Use `tmp_path` fixtures in pytest for isolated `flights.db` instances.
- **Coverage:** Includes unit tests for pure logic, integration tests for the orchestrator, and config validation checks.