# Copenhagen Flight Tracker

A self-hosted Python service that tracks one-way flight prices between Copenhagen (CPH) and Amsterdam (AMS) in both directions. It scrapes Google Flights via the [`fast-flights`](https://github.com/AWeirdDev/flights) library (Protobuf-based, no browser needed), stores every observed price in SQLite, and spreads requests evenly across a configurable daily window to avoid IP bans (hopefully). An easy overview with the cheapest flights will be hosted on jensbremer.nl (eventually)

## Install

**Mac / Linux**
```bash
git clone https://github.com/Jens-Bremer/copenhagen-flight-tracker.git
cd copenhagen-flight-tracker
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -c "import os; os.makedirs('data', exist_ok=True); os.makedirs('logs', exist_ok=True)"
python scripts/setup_db.py
```

**Windows** (Command Prompt or PowerShell)
```bat
git clone https://github.com/Jens-Bremer/copenhagen-flight-tracker.git
cd copenhagen-flight-tracker
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -c "import os; os.makedirs('data', exist_ok=True); os.makedirs('logs', exist_ok=True)"
python scripts\setup_db.py
```

## Configuration

### Notifications (optional)

Open `config.py` and set your topic name:

```python
NTFY_TOPIC = "your-unique-topic-name"
```

Then on your phone:
1. Install the [ntfy app](https://ntfy.sh) (free, iOS & Android).
2. Tap **+** and subscribe to the exact same topic name.
3. You will receive alerts for price drops and system anomalies.

Notes:
- Your ntfy topic is effectively public by default. Anyone who knows the topic name can subscribe and receive your alerts.
- If you want to disable notifications entirely, set `NTFY_TOPIC = ""`.

### Price alerts

Set route-specific thresholds in `config.PRICE_ALERT_THRESHOLD` (values in cents). When a scraped flight falls below its threshold, you get an ntfy notification after the daily collection finishes.

### Other settings

All other tuneable values — routes, date range, pacing window, database path, health thresholds — are in `config.py`. Invalid configurations are caught and reported at startup before any work begins. This tool is specifically made for short flights within Europe. Not sure how well the tool handles different timezones, or flights with a layover.

## Running the tracker

### Recommended: continuous scheduler (any OS)

Run a single command and leave it running. It handles all timing automatically — no cron or Task Scheduler needed:

```bash
python scripts/run_scheduler.py
```

This registers five jobs:
- **Daily collection** — fires at 06:00 every day, spreads all requests across the day until 22:00
- **Database backup** — fires at 01:00, snapshots `data/flights.db` and prunes old backups
- **Health check** — fires at 23:30, alerts via ntfy if anything looks wrong
- **CSV export** — fires at 23:45, writes `data/flights_export.csv` for archival
- **Frontend CSV** — fires at 23:46, writes `data/flights_frontend.csv` for browser ingestion

Keep the terminal open, or run it in the background with `nohup` / as a system service.

### Alternative: manual one-off run

To do a single collection run immediately (useful for testing):

```bash
python scripts/run_daily.py
```

The script waits until 06:00 if the window has not opened yet, then spaces requests across the day until 22:00. Press `Ctrl+C` to stop early.

## CSV export

`data/flights_export.csv` is regenerated automatically every night at 23:45. It contains all stored observations with columns: `retrieved_at`, `departure_date`, `origin`, `destination`, `airline`, `departure_time`, `arrival_time`, `price_amount`, `price_currency`. This file is intended for archival completeness and downstream tooling.

A slimmer derivative — `data/flights_frontend.csv` — is built one minute later at 23:46 (`scripts/build_frontend_csv.py`). It carries machine-typed datetimes, precomputed `duration_minutes`, and `price_cents`, sorted deterministically; it is the file the frontend should fetch.

To generate either manually at any time:

```bash
python scripts/export_csv.py
python scripts/build_frontend_csv.py
```

## Inspecting data

```bash
# Summary: total rows, date range, per-route counts
python scripts/query_prices.py --stats

# Cheapest observed price per route for each upcoming departure date
python scripts/query_prices.py --cheapest

# Full price history for a specific departure date
python scripts/query_prices.py --date YYYY-MM-DD
```

## License

MIT

_( i have not clue how this works, just take your own repsonsibilty )_
