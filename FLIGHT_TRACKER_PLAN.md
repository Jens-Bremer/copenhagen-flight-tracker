# Flight Price Tracker — Build Plan

## Project Goal

Build a self-hosted Python service that tracks **one-way flight prices between Copenhagen (CPH) and Amsterdam (AMS) in both directions** over time. It scrapes Google Flights via the `fast-flights` library (Protobuf-based, no browser needed), stores every observed price in SQLite, and spreads its requests throughout the day to avoid IP bans.

### MVP Scope

- Only one-way flights (no round trips). **Both directions**: CPH → AMS and AMS → CPH.
- Only flights departing on **Friday, Saturday, or Sunday**.
- Only dates within the **next 6 months** from today.
- One full scrape cycle per day, with requests **evenly spaced** across a configurable time window (default: 06:00–22:00).
- Store **one row per flight per observation** — full flight details plus the exact UTC timestamp of retrieval.
- SQLite database, single file, no external DB server.
- Cron triggers a single daily run script; the script handles its own internal pacing.

---

## Repository Structure

Create exactly this structure. Every file listed below must exist.

```
flight-tracker/
├── README.md                     # Project description, setup, usage
├── requirements.txt              # Pinned dependencies
├── config.py                     # All tuneable constants (single source of truth)
├── src/
│   ├── __init__.py               # Empty
│   ├── date_generator.py         # Compute which dates to query
│   ├── route_expander.py         # Combine routes × dates into a flat job list
│   ├── flight_fetcher.py         # Wrap fast-flights, one query at a time
│   ├── response_parser.py        # Extract structured rows from raw result
│   ├── database.py               # SQLite schema, insert, read helpers
│   ├── request_pacer.py          # Calculate sleep intervals, enforce pacing
│   ├── notifier.py               # Send alerts via ntfy.sh
│   └── health_checker.py         # Post-run diagnostics: detect anomalies
├── scripts/
│   ├── setup_db.py               # One-off: create database + tables
│   ├── run_daily.py              # Entry point: orchestrates one full daily cycle
│   ├── run_health_check.py       # Entry point: post-run health check (separate cron)
│   └── query_prices.py           # CLI utility to inspect stored data
└── tests/
    ├── __init__.py               # Empty
    ├── test_date_generator.py    # Unit tests for date logic
    ├── test_response_parser.py   # Unit tests for parsing
    └── test_request_pacer.py     # Unit tests for pacing math
```

---

## Task Checklist

Work through these tasks **in order**. Each task is self-contained. Commit after each task.

---

### Task 1 — Initialize the repository

- [ ] Create the full directory tree shown above.
- [ ] Create `requirements.txt` with these pinned dependencies:

```
fast-flights>=2.0
```

- [ ] Create an empty `src/__init__.py` and `tests/__init__.py`.
- [ ] Create `README.md` with a one-paragraph project description, install instructions (`pip install -r requirements.txt`), and a "Usage" section that says "See below — filled in after MVP is complete."

**Acceptance:** `tree` output matches the structure above. `pip install -r requirements.txt` succeeds.

---

### Task 2 — `config.py`

- [ ] Create `config.py` in the project root. It holds **every tuneable value** as a module-level constant. No other file may hardcode these values.

```python
# config.py — single source of truth for all tuneable parameters

# --- Routes (each is a one-way direction) ---
ROUTES = [
    ("CPH", "AMS"),
    ("AMS", "CPH"),
]

# --- Date scope ---
DEPARTURE_WEEKDAYS = [4, 5, 6]  # Monday=0 ... Friday=4, Saturday=5, Sunday=6
MAX_MONTHS_AHEAD = 6

# --- Scraping ---
SEAT_CLASS = "economy"
PASSENGERS_ADULTS = 1
TRIP_TYPE = "one-way"

# --- Pacing ---
DAILY_WINDOW_START_HOUR = 6   # Local server time, 06:00
DAILY_WINDOW_END_HOUR = 22    # Local server time, 22:00

# --- Storage ---
DATABASE_PATH = "data/flights.db"

# --- Notifications (ntfy.sh) ---
NTFY_TOPIC = "your-secret-topic-name-here"  # Change this to a unique random string
NTFY_URL = "https://ntfy.sh"
```

**Acceptance:** Importing `config` works. All downstream tasks reference `config.X` instead of literals.

---

### Task 3 — `src/date_generator.py`

- [ ] Implement **one function**: `generate_target_dates(today: date) -> list[date]`
- [ ] It returns a sorted list of all dates from `today` through `today + MAX_MONTHS_AHEAD months` that fall on one of the `DEPARTURE_WEEKDAYS`.
- [ ] Use `dateutil.relativedelta` (add to `requirements.txt`) to compute "6 months from today" correctly (not 180 days).
- [ ] No side effects. Pure function. Import weekdays and month range from `config`.

**Acceptance:** `test_date_generator.py` passes with at least these tests:
- Returns only Fri/Sat/Sun dates.
- First date is >= today.
- Last date is <= 6 months from today.
- List is sorted ascending.
- No duplicates.

---

### Task 4 — `src/route_expander.py`

- [ ] Implement **one function**: `expand_jobs(routes: list[tuple[str, str]], dates: list[date]) -> list[tuple[str, str, date]]`
- [ ] Returns the cartesian product: every route combined with every date. Each tuple is `(origin, destination, departure_date)`.
- [ ] Shuffle the output so that CPH→AMS and AMS→CPH requests for the same date are not back-to-back. This makes the request pattern look less robotic.
- [ ] Use `random.shuffle` with a daily seed (`random.seed(today.toordinal())`) so the order is deterministic within a day but varies day-to-day.
- [ ] Pure function apart from the shuffle.

**Pacing note:** 2 routes × ~78 dates = ~156 requests. Over 16 hours = one request every ~6 minutes. Still safe.

**Acceptance:** Output length equals `len(routes) * len(dates)`. Both routes appear. All dates appear. Order is shuffled (not grouped by route or sorted by date).

---

### Task 5 — `src/flight_fetcher.py`

- [ ] Implement **one function**: `fetch_flights_for_date(origin: str, destination: str, departure_date: date) -> Result`
- [ ] It calls `fast_flights.get_flights()` with the given origin, destination, seat, passengers, and `trip="one-way"`.
- [ ] It passes `fetch_mode="fallback"` to handle occasional empty responses.
- [ ] On any exception, it logs the error and returns `None` (fail fast, but don't crash the whole daily run).
- [ ] Uses Python's `logging` module, not `print`.

**Acceptance:** Calling it with `("CPH", "AMS", tomorrow)` returns a `Result` object (or `None` if Google is temporarily uncooperative). Logged output shows the route and date being queried.

---

### Task 6 — `src/response_parser.py`

- [ ] Implement **one function**: `parse_flights(result: Result, origin: str, destination: str, departure_date: date, retrieved_at: datetime) -> list[dict]`
- [ ] It takes a `fast-flights` `Result` and returns a list of flat dictionaries, one per flight.
- [ ] Each dictionary must contain **exactly these keys**:

| Key                  | Type     | Description                                      |
|----------------------|----------|--------------------------------------------------|
| `retrieved_at`       | str      | ISO 8601 UTC timestamp of when the scrape ran    |
| `departure_date`     | str      | YYYY-MM-DD                                       |
| `origin`             | str      | Airport IATA code (from function argument)       |
| `destination`        | str      | Airport IATA code (from function argument)       |
| `airline`            | str      | Airline name(s) from the result                  |
| `departure_time`     | str      | Departure time as returned by the API            |
| `arrival_time`       | str      | Arrival time as returned by the API              |
| `duration`           | str      | Flight duration as returned by the API           |
| `stops`              | int      | Number of stops (0 = direct)                     |
| `price`              | str      | Raw price string as returned (e.g. "€89")        |
| `price_amount`       | int/None | Extracted numeric price in cents, or None         |
| `price_currency`     | str/None | Extracted currency code (e.g. "EUR"), or None     |
| `is_best`            | bool     | Whether Google flagged it as "best"               |
| `current_price_trend`| str/None | Result.current_price ("low"/"typical"/"high")     |

- [ ] Implement a **helper function**: `extract_price_parts(raw_price: str) -> tuple[int | None, str | None]` to parse "€89" into `(8900, "EUR")`, "$120" into `(12000, "USD")`, etc. Handle `None` gracefully.
- [ ] If `result` is `None`, return an empty list.

**Acceptance:** `test_response_parser.py` covers:
- Normal flight with all fields present.
- Flight with missing price.
- `None` result input returns `[]`.
- `extract_price_parts` handles €, $, and unknown symbols.

---

### Task 7 — `src/database.py`

- [ ] Implement **three functions**:
  1. `initialize_database(db_path: str) -> None` — Creates the database file + directory if needed. Creates the `flight_observations` table with a schema matching the dict from Task 6. Add an auto-increment `id` primary key. Add an index on `(origin, destination, departure_date, airline, departure_time)` for fast lookups.
  2. `insert_observations(db_path: str, observations: list[dict]) -> int` — Inserts a batch of observation dicts. Returns the count of rows inserted. Uses a single transaction.
  3. `query_price_history(db_path: str, departure_date: str, origin: str | None = None, destination: str | None = None, airline: str | None = None) -> list[dict]` — Returns all observations for a given departure date, optionally filtered by route and/or airline, ordered by `retrieved_at` ascending.

- [ ] Use `sqlite3` from the standard library. No ORM.
- [ ] Every function opens and closes its own connection (no shared state).

**Acceptance:** `setup_db.py` (next task) runs without error. Manual insert + query round-trips correctly.

---

### Task 8 — `scripts/setup_db.py`

- [ ] A short script that imports `database.initialize_database` and `config.DATABASE_PATH`, calls it, and prints confirmation.
- [ ] Idempotent: running it twice does not error (use `CREATE TABLE IF NOT EXISTS`).

**Acceptance:** Running `python scripts/setup_db.py` creates `data/flights.db`. Running it again prints the same confirmation without error.

---

### Task 9 — `src/request_pacer.py`

- [ ] Implement **one function**: `compute_sleep_intervals(num_requests: int, window_start_hour: int, window_end_hour: int) -> list[float]`
- [ ] Given N requests and a time window, returns a list of N-1 sleep durations (in seconds) to evenly space the requests.
- [ ] Add a small random jitter (±10%) to each interval to avoid a predictable pattern.
- [ ] Implement **one function**: `seconds_until_window_start(window_start_hour: int) -> float`
- [ ] Returns how many seconds from `now` until the next occurrence of `window_start_hour` local time. Returns `0.0` if already inside the window.

**Acceptance:** `test_request_pacer.py` covers:
- 10 requests over 16 hours → ~9 intervals of ~6400 seconds each (± jitter).
- Jitter stays within ±10%.
- 1 request → empty interval list.
- `seconds_until_window_start` returns 0 when inside the window.

---

### Task 10 — `scripts/run_daily.py`

This is the **orchestrator**. It ties everything together. It is the only script the cron job calls.

- [ ] On startup, log the current time and "Starting daily flight price collection".
- [ ] Step 1: Call `generate_target_dates(date.today())` to get all target departure dates.
- [ ] Step 2: Call `expand_jobs(config.ROUTES, dates)` to get the flat job list (route × date tuples).
- [ ] Step 3: Call `compute_sleep_intervals(len(jobs), ...)` to get pacing intervals.
- [ ] Step 4: If currently before the window start, call `seconds_until_window_start` and sleep until the window opens.
- [ ] Step 5: Loop through each job `(origin, destination, departure_date)`:
  - Log which job is being queried and the progress (e.g. "Querying CPH→AMS 2025-09-19 [14/156]").
  - Call `fetch_flights_for_date(origin, destination, departure_date)`.
  - Call `parse_flights(result, origin, destination, departure_date, datetime.utcnow())`.
  - Call `insert_observations(config.DATABASE_PATH, observations)`.
  - Log how many flights were stored.
  - If not the last job, sleep for the next interval.
- [ ] Step 6: Log "Daily collection complete. Total observations: X. Failed jobs: Y."
- [ ] Track failed jobs (date + route that returned zero results) and log them at the end.
- [ ] Wrap each iteration in try/except so a single failed job doesn't kill the run. Log the failure and continue.
- [ ] Configure logging at the top: level=INFO, format includes timestamp.
- [ ] Write a heartbeat file (`data/last_run.json`) at the end with: `run_date`, `total_observations`, `failed_jobs_count`, `duration_seconds`.

**Acceptance:** Running `python scripts/run_daily.py` fetches flight data for all routes and target dates, stores it in SQLite, and takes many hours to complete (due to pacing). Can be interrupted with Ctrl+C gracefully.

---

### Task 11 — `scripts/query_prices.py`

- [ ] A CLI tool using `argparse` with these commands:
  - `python scripts/query_prices.py --date 2025-09-19` — Show all price observations for that departure date, both directions, grouped by route+airline+departure_time, showing the price over time.
  - `python scripts/query_prices.py --cheapest` — Show the cheapest observed price per direction for each upcoming departure date.
  - `python scripts/query_prices.py --stats` — Show total rows in DB, date range covered, number of unique departure dates tracked, split by route direction.
- [ ] Output is plain text, formatted for terminal readability.

**Acceptance:** After at least one `run_daily.py` run, all three commands produce meaningful output.

---

### Task 12 — Cron setup documentation

- [ ] Update `README.md` with:
  - Full install instructions (clone, venv, pip install, setup_db).
  - How to do a manual test run.
  - Crontab lines for both the daily run and the health check:
    ```
    55 5 * * * cd /path/to/flight-tracker && /path/to/venv/bin/python scripts/run_daily.py >> logs/daily.log 2>&1
    30 23 * * * cd /path/to/flight-tracker && /path/to/venv/bin/python scripts/run_health_check.py >> logs/health.log 2>&1
    ```
  - How to inspect data with `query_prices.py`.
  - Note about creating `logs/` and `data/` directories.
  - Instructions for setting up ntfy.sh topic (subscribe on phone, set topic in config).

**Acceptance:** A new user can follow the README from scratch and have it running within 10 minutes.

---

### Task 13 — Write all tests

- [ ] `tests/test_date_generator.py` — As specified in Task 3.
- [ ] `tests/test_response_parser.py` — As specified in Task 6.
- [ ] `tests/test_request_pacer.py` — As specified in Task 9.
- [ ] All tests use `pytest`. Add `pytest` to `requirements.txt`.
- [ ] Tests must not make real HTTP requests. Mock `fast-flights` responses where needed.

**Acceptance:** `pytest tests/` passes with 0 failures.

---

### Task 14 — `src/notifier.py` and `src/health_checker.py`

**`src/notifier.py`:**

- [ ] Implement **one function**: `send_alert(title: str, message: str, priority: str = "default") -> bool`
- [ ] Sends a POST to `{config.NTFY_URL}/{config.NTFY_TOPIC}` with the title and message.
- [ ] Uses `urllib.request` (stdlib) — no extra dependency needed.
- [ ] Supports ntfy priority levels: `"min"`, `"low"`, `"default"`, `"high"`, `"urgent"`.
- [ ] Returns `True` on success, `False` on failure (logs the error, never raises).
- [ ] If `NTFY_TOPIC` is empty or `None`, silently skip (notifications disabled).

**`src/health_checker.py`:**

- [ ] Implement **one function**: `run_health_check(db_path: str) -> list[str]`
- [ ] Returns a list of problem descriptions (empty list = everything is fine).
- [ ] Checks the following, in order:

| Check                          | Problem condition                                                      | Severity |
|--------------------------------|------------------------------------------------------------------------|----------|
| **Heartbeat stale**            | `data/last_run.json` is missing or its `run_date` is not today         | urgent   |
| **Run had high failure rate**  | `failed_jobs_count / total_jobs > 0.25` (more than 25% failed)         | high     |
| **Zero observations today**    | No rows with today's date in `retrieved_at`                            | urgent   |
| **Observation count drop**     | Today's total observations < 50% of the average of the last 7 days     | high     |
| **Currency inconsistency**     | More than one distinct `price_currency` seen in today's observations   | default  |

- [ ] Each check is a **separate private function** that returns `str | None`.
- [ ] `run_health_check` calls them all, collects non-None results, and returns the list.

---

### Task 15 — `scripts/run_health_check.py`

- [ ] Entry point for the health check cron job. Runs after the daily collection window closes (e.g. 23:30).
- [ ] Calls `run_health_check(config.DATABASE_PATH)`.
- [ ] If problems were found, calls `send_alert` once with all problems joined into a single message. Uses the highest severity from the problems as the ntfy priority.
- [ ] If no problems, does nothing (no "all clear" spam — only notify when something is wrong).
- [ ] Logs all results regardless.

**Acceptance:** Manually deleting `data/last_run.json` and running `python scripts/run_health_check.py` triggers a notification to your ntfy topic with "Heartbeat stale" in the message.

---

## Design Rules (enforce throughout)

1. **One function, one job.** If a function does two things, split it.
2. **No hardcoded values.** Everything tuneable lives in `config.py`.
3. **Meaningful names.** `fetch_flights_for_date`, not `fetch` or `get_data`.
4. **Fail fast.** Validate inputs at function boundaries. Raise or return early.
5. **No repetition.** If logic appears twice, extract it.
6. **Simple over clever.** No metaprogramming, no decorators-for-the-sake-of-it.
7. **Readability first.** Blank lines between logical blocks. Docstrings on every public function.
8. **Logging, not printing.** Use the `logging` module everywhere except `query_prices.py` (CLI output).
9. **Type hints on every function signature.**
10. **Each `src/` module imports only from `config` and standard library / installed packages.** No circular imports between `src/` modules.
