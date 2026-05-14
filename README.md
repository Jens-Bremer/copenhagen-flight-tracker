# Copenhagen Flight Tracker

A self-hosted Python service that tracks one-way flight prices between Copenhagen (CPH) and Amsterdam (AMS) in both directions. It scrapes Google Flights via the [`fast-flights`](https://github.com/AWeirdDev/flights) library (Protobuf-based, no browser needed), stores every observed price in SQLite, and spreads its ~156 daily requests evenly across a configurable time window to avoid IP bans.

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
3. You will receive an alert if the tracker stops working or detects anomalies.

Set `NTFY_TOPIC = ""` to disable notifications.

### Other settings

All other tuneable values — routes, date range, pacing window, database path — are in `config.py`.

## Running the tracker

### Recommended: continuous scheduler (any OS)

Run a single command and leave it running. It handles all timing automatically — no cron or Task Scheduler needed:

```bash
python scripts/run_scheduler.py
```

This starts the daily price collection at 06:00 every day and runs the health check at 23:30. Keep the terminal open (or run it in the background / as a service).

### Alternative: manual one-off run

To do a single collection run immediately (useful for testing):

```bash
python scripts/run_daily.py
```

The script waits until 06:00 if the window has not opened yet, then spaces requests across the day until 22:00. Press `Ctrl+C` to stop early.

### Alternative: cron (Mac / Linux only)

Add these two lines to your crontab (`crontab -e`), adjusting the paths:

```
55 5 * * * cd /path/to/copenhagen-flight-tracker && /path/to/.venv/bin/python scripts/run_daily.py >> logs/daily.log 2>&1
30 23 * * * cd /path/to/copenhagen-flight-tracker && /path/to/.venv/bin/python scripts/run_health_check.py >> logs/health.log 2>&1
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
