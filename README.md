# Copenhagen Flight Tracker

A self-hosted Python service that tracks one-way flight prices between Copenhagen (CPH) and Amsterdam (AMS) in both directions. It scrapes Google Flights via the [`fast-flights`](https://github.com/AWeirdDev/flights) library (Protobuf-based, no browser needed), stores every observed price in SQLite, and spreads requests evenly across a configurable daily window to avoid IP bans. An overview of the data is presented on [jensbremer.nl](https://stats.jensbremer.nl/copenhagen-flight-tracker/frontend/)

## Install

**Mac / Linux**
```bash
git clone https://github.com/Jens-Bremer/copenhagen-flight-tracker.git
cd copenhagen-flight-tracker
python3 -m venv .venv
source .venv/bin/activate
pip install -e .            # production
# pip install -e ".[dev]"   # development (adds pytest + ruff)
python scripts/setup_db.py
```

**Windows** (Command Prompt or PowerShell)
```bat
git clone https://github.com/Jens-Bremer/copenhagen-flight-tracker.git
cd copenhagen-flight-tracker
python -m venv .venv
.venv\Scripts\activate
pip install -e .            :: production
:: pip install -e ".[dev]"  :: development (adds pytest + ruff)
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

## First run

After install, generate a dashboard you can open right now:

```bash
python scripts/setup_db.py
python scripts/run_daily.py            # ~3-5 minutes to collect a small sample
python scripts/build_frontend_csv.py
python scripts/generate_html.py
open frontend/index.html               # macOS; xdg-open on Linux; start on Windows
```

For ongoing collection, use the scheduler — see below.

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

## Deploying as a service

Ready-made deployment files are provided under `deploy/` for Linux systems using systemd.

```bash
# 1. Clone and install (one-time setup)
sudo mkdir -p /opt/copenhagen-flight-tracker
sudo chown flighttracker:flighttracker /opt/copenhagen-flight-tracker
git clone https://github.com/Jens-Bremer/copenhagen-flight-tracker.git /opt/copenhagen-flight-tracker
cd /opt/copenhagen-flight-tracker
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
python scripts/setup_db.py

# 2. Install the systemd unit
sudo cp deploy/copenhagen-flight-tracker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now copenhagen-flight-tracker

# 3. (Optional) Install logrotate config
sudo cp deploy/copenhagen-flight-tracker.logrotate /etc/logrotate.d/
```

The scheduler handles `SIGTERM` gracefully — `systemctl stop` will shut it down cleanly.

## CSV export

`data/flights_export.csv` is regenerated automatically every night at 23:45. It contains all stored observations with columns: `retrieved_at`, `departure_date`, `origin`, `destination`, `airline`, `departure_time`, `arrival_time`, `price_amount`, `price_currency`. This file is intended for archival completeness and downstream tooling.

A slimmer derivative — `data/flights_frontend.csv` — is built one minute later at 23:46 (`scripts/build_frontend_csv.py`). It carries machine-typed datetimes, precomputed `duration_minutes`, and `price_cents`, sorted deterministically; it is the file the frontend should fetch.

To generate either manually at any time:

```bash
python scripts/export_csv.py
python scripts/build_frontend_csv.py
```

## Frontend

A self-contained static dashboard is regenerated every night and written to `frontend/index.html`. It runs inline at the end of the 23:46 frontend CSV job — no separate timed entry, so a slow CSV build can never leave the page stale or trigger a race against the clock. Open the output directly in a browser:

```bash
open frontend/index.html        # macOS
xdg-open frontend/index.html    # Linux
```

The page works fully offline — Chart.js is committed under `frontend/vendor/` and inlined into the output by the generator. Only the DM Sans / DM Serif Display fonts are loaded from Google Fonts; system-font fallbacks kick in when offline.

### Manual regeneration

```bash
python scripts/generate_html.py
```

Reads `data/flights_frontend.csv` and writes `frontend/index.html`. Use `--input` / `--output` to override.

### Initial setup (one-time)

```bash
python scripts/fetch_vendor.py
```

Downloads Chart.js 4.4.3 into `frontend/vendor/chart.min.js`. Already done in a fresh clone — re-run only when bumping the Chart.js version.

### What's in the dashboard

- **Calendar** — every departure date in the data window, colour-tinted on a shared green→red scale by cheapest observed price.
- **Drill-down** — click a date to see all flights that day; click a flight to see its price-over-time chart with gaps preserved.
- **Price trends** — market trend (cheapest seen on each scrape day) and lead-time curve (mean price by days-before-departure) with a sweet-spot annotation.
- **Airline histograms** — €5 bins, one bar per airline using brand colours.
- **Weekend pairs** — top 5 Fri-out + Sun-back pairs sorted by total price.
- **Cheapness footer** — cheapest day-of-week and cheapest month.

All five panels react to the route toggle (CPH-AMS / AMS-CPH / both) and the airline filter chips above the calendar.

## Inspecting data

```bash
# Summary: total rows, date range, per-route counts
python scripts/query_prices.py --stats

# Cheapest observed price per route for each upcoming departure date
python scripts/query_prices.py --cheapest

# Full price history for a specific departure date
python scripts/query_prices.py --date YYYY-MM-DD
```

## Troubleshooting

**Scheduler stops collecting at midnight** — check the heartbeat at `data/last_run.json` and the daily log in `logs/tracker.log`.

**Dashboard shows "Not enough data yet"** — early days; needs at least `RELIABLE_MIN_OBSERVATIONS` per lead-time bucket (default 10) for the When-to-book card.

**No ntfy alerts arriving** — check `NTFY_TOPIC` in `config.py` is not the placeholder `your-topic-here`; the topic must match exactly between `config.py` and your ntfy app subscription.

**Health check reports "Bot challenge today"** — Google may have rotated the cookie-consent flow. See `src/flight_fetcher.py:patched_fetch` and issue #110.

## Architecture

- [`CLAUDE.md`](CLAUDE.md) — module contract, key design rules, commands cheatsheet.
- [`docs/FRONTEND.md`](docs/FRONTEND.md) — frontend pipeline, JSON contract, Chart.js layout.

### Note on stability

The scraper depends on a hard-coded `SOCS=CAI; CONSENT=PENDING+999` cookie pair in `src/flight_fetcher.py` to bypass Google's EU consent wall. If Google changes that format, scraping silently degrades. The `#111` ban-signal classifier and `#110` cookie-consent alert are the early-warning surfaces; see `docs/FRONTEND.md` and `CLAUDE.md` for the broader architecture.

## Contributing

See [`CLAUDE.md`](CLAUDE.md) for module-contract rules and the project's code conventions. A formal `CONTRIBUTING.md` is filed as issue #131.

## License

MIT — see LICENSE.
