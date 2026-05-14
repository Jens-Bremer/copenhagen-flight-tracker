# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Self-hosted Python service that tracks one-way CPH↔AMS flight prices by scraping Google Flights via `fast-flights` (Protobuf-based, no browser). Prices are stored in SQLite with one row per flight per observation. A cron job triggers `scripts/run_daily.py` once per day; the script paces its own requests evenly across a 06:00–22:00 window.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Initialize the database (idempotent)
python scripts/setup_db.py

# Run the daily collection (takes many hours due to pacing)
python scripts/run_daily.py

# Run the health check (run after 22:00)
python scripts/run_health_check.py

# Query stored data
python scripts/query_prices.py --date YYYY-MM-DD
python scripts/query_prices.py --cheapest
python scripts/query_prices.py --stats

# Run tests
pytest tests/

# Run a single test file
pytest tests/test_date_generator.py
```

## Architecture

All tuneable values live exclusively in `config.py` — no other file may hardcode routes, weekday filters, pacing windows, database path, or ntfy settings.

### Data flow

```
date_generator → route_expander → flight_fetcher → response_parser → database
                                       ↑                   ↑
                                   request_pacer        notifier/health_checker
```

`scripts/run_daily.py` is the only orchestrator; `scripts/run_health_check.py` runs separately via its own cron entry at 23:30.

### Module contract

Each `src/` module imports only from `config` and stdlib/installed packages — no cross-imports between `src/` modules. Every public function has type hints and a docstring.

### Key design rules

- **No hardcoded values** — all constants reference `config.X`.
- **Logging everywhere** (`logging` module), except `scripts/query_prices.py` which uses plain `print`.
- **Fail gracefully in the loop** — a single failed fetch should be caught and counted, not crash the daily run. Failed jobs are reported at the end and written to `data/last_run.json`.
- **Pure functions in `src/`** — side effects (DB writes, HTTP calls, sleeps) stay in `scripts/`.
- **`request_pacer.py` adds ±10% jitter** to each sleep interval to avoid predictable request patterns.
- **`route_expander.py` shuffles** the job list with a daily seed so CPH→AMS and AMS→CPH requests for the same date are not back-to-back.

### Database

SQLite at `data/flights.db`. Schema: `flight_observations` table with an auto-increment `id` and an index on `(origin, destination, departure_date, airline, departure_time)`. Every function in `database.py` opens and closes its own connection.

### Notifications

`notifier.py` posts to ntfy.sh using only `urllib.request` (stdlib). If `NTFY_TOPIC` is empty/None, notifications are silently skipped.

### Tests

Tests live in `tests/` and use `pytest`. No real HTTP requests — mock `fast-flights` responses. Three test files cover: `date_generator`, `response_parser`, and `request_pacer`.
