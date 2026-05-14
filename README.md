# Copenhagen Flight Tracker

A self-hosted Python service that tracks one-way flight prices between Copenhagen (CPH) and Amsterdam (AMS) in both directions. It scrapes Google Flights via the [`fast-flights`](https://github.com/AWeirdDev/flights) library (Protobuf-based, no browser needed), stores every observed price in SQLite, and spreads its ~156 daily requests evenly across a configurable time window to avoid IP bans.

## Install

```bash
git clone https://github.com/Jens-Bremer/copenhagen-flight-tracker.git
cd copenhagen-flight-tracker
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
mkdir -p data logs
python scripts/setup_db.py
```

## Configuration

Open `config.py` and set your ntfy.sh topic before first use:

```python
NTFY_TOPIC = "your-secret-topic-name-here"  # replace with a unique random string
```

To receive alerts on your phone: install the [ntfy app](https://ntfy.sh), tap **+**, and subscribe to the same topic name. Leave `NTFY_TOPIC` empty to disable notifications.

All other tuneable values (routes, date range, pacing window, database path) are in `config.py`.

## Manual test run

To verify everything works before setting up cron, run the daily collector directly. It will start scraping immediately (bypassing the 06:00 window) if the window has already opened, or wait until 06:00 if run earlier:

```bash
source .venv/bin/activate
python scripts/run_daily.py
```

Press `Ctrl+C` to stop. Check what was collected:

```bash
python scripts/query_prices.py --stats
python scripts/query_prices.py --cheapest
python scripts/query_prices.py --date 2025-09-19
```

## Cron setup

Add these two lines to your crontab (`crontab -e`), adjusting the paths:

```
# Daily price collection — starts at 05:55, waits for 06:00 window, finishes ~22:00
55 5 * * * cd /path/to/copenhagen-flight-tracker && /path/to/.venv/bin/python scripts/run_daily.py >> logs/daily.log 2>&1

# Health check — runs after the collection window closes
30 23 * * * cd /path/to/copenhagen-flight-tracker && /path/to/.venv/bin/python scripts/run_health_check.py >> logs/health.log 2>&1
```

The `logs/` directory must exist before cron runs (created above in the install step).

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
