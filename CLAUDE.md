# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Philosophy & Current State

A self-hosted, extremely fault-tolerant Python service that tracks flight prices by scraping Google Flights via `fast-flights`. The core philosophy is **reliable passive data collection without IP bans** to eventually answer the question: *"When should I buy my ticket?"*

Currently, the project operates as a robust MVP:
- **Scheduler-driven:** A single Python daemon (`run_scheduler.py`) manages its own daily pacing and health checks. No OS-level cron is required.
- **Fault-tolerant:** Transient network errors or single-flight failures do not crash the daily scrape.
- **Strictly configured:** All settings are strictly validated on startup. Local overrides live in `config_local.py`.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Initialize the database (safe to run multiple times)
python scripts/setup_db.py

# Run the continuous daemon (orchestrates daily scrape + nightly health check)
python scripts/run_scheduler.py

# Query stored data via CLI
python scripts/query_prices.py --stats
python scripts/query_prices.py --cheapest
python scripts/query_prices.py --date YYYY-MM-DD

# Run the complete test suite (121+ tests)
pytest tests/
```

## Architecture & Workflow

### Orchestration
`scripts/run_scheduler.py` is the continuous daemon. It schedules two main jobs:
1. `_daily_job` (via `scripts/run_daily.py`): Expands routes/dates, paces requests, fetches, parses, and inserts.
2. `_health_check_job` (via `src/health_checker.py`): Validates database integrity nightly and alerts via `ntfy` if anomalies occur.

### Data Flow
```
date_generator → route_expander → flight_fetcher → response_parser → database
                                       ↑                   ↑
                                   request_pacer        notifier/health_checker
```

### Module Contract
Each `src/` module imports only from `config` and stdlib/installed packages — **no cross-imports between `src/` modules**. Every public function has type hints and a docstring. Pure functions stay in `src/`, while side effects (DB writes, HTTP calls, sleeps) are orchestrated in `scripts/`.

## Key Design Rules

1. **No hardcoded values:** All constants reference `config.X`.
2. **Local Overrides:** `config_local.py` is gitignored. Use it for local deployments to set `NTFY_TOPIC` or override pacing windows without creating Git conflicts.
3. **Pacing & Jitter:** `request_pacer.py` adds ±10% jitter to evenly space requests across a daily window to look organic. `route_expander.py` shuffles jobs to avoid sequential identical routes.
4. **Logging everywhere:** The `logging` module is configured via `src/log_config.py`. Exception: `query_prices.py` uses plain `print` for CLI readability.

## Database & Migrations

SQLite at `data/flights.db`. 
- **Schema:** `flight_observations` table with an auto-increment `id` and a multi-column lookup index.
- **Rule for Updates:** **Never break historical data.** If adding features (e.g., Layovers, Round Trips), add new columns as `NULLABLE` so historical rows seamlessly parse, or create new tables entirely. Avoid renaming or deleting columns.

## Tests

The test suite relies heavily on `pytest` and `unittest.mock`. 
- **No real HTTP requests:** Always mock `fast-flights` API calls.
- **No real DB state:** Use `tmp_path` fixtures in pytest for isolated `flights.db` instances.
- **Coverage:** Includes unit tests for pure logic, integration tests for the orchestrator, and config validation checks.