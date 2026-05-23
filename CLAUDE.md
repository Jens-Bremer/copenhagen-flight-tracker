# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Philosophy & Current State

A self-hosted, extremely fault-tolerant Python service that tracks flight prices by scraping Google Flights via `fast-flights`. The core philosophy is **reliable passive data collection without IP bans** to eventually answer the question: *"When should I buy my ticket?"*

Currently, the project operates as a mature service with a full analytics frontend:
- **Scheduler-driven:** A single Python daemon (`run_scheduler.py`) manages its own daily pacing, health checks, backups, CSV exports, and frontend regeneration. No OS-level cron is required.
- **Fault-tolerant:** Transient network errors or single-flight failures do not crash the daily scrape. A two-pass retry system handles transient failures.
- **Strictly configured:** All settings live in `config.py`. All values are validated at startup before any work begins.
- **Browser-automated:** The HTTP transport layer uses a real Chromium browser (Playwright) rather than a raw HTTP client. `fast_flights.core.fetch` is monkey-patched at startup with `browser_fetch` from `src/browser_fetcher.py`.

## Commands

```bash
# Install dependencies (production)
pip install -e .

# Install with dev extras (pytest, ruff)
pip install -e ".[dev]"

# Install Chromium browser (required — one-time, must be run after pip install)
playwright install chromium

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
                                       ↑                        ↓
                                  browser_fetcher          health_checker
                                 (direct | proxy)               ↓
                                       ↑              analytics → html_generator → frontend/index.html
                              fast_flights.core.fetch
                              (monkey-patched at startup)
```

### Frontend Pipeline
The static dashboard is regenerated nightly with zero runtime fetches:
1. `src/frontend_csv_builder.py` reads the DB and writes `data/flights_frontend.csv` (slim, typed, sorted).
2. `src/html_generator.py` reads that CSV, computes analytics (`src/analytics.py`), and writes `frontend/index.html`.
3. Chart.js is vendored under `frontend/vendor/` and inlined into the HTML at build time.
4. The browser runs `frontend/app.js` (IIFE) against five embedded JSON blobs — no network requests needed.

### Module Contract
Each `src/` module imports only from `config` and stdlib/installed packages — **no cross-imports between `src/` modules** except for the analytics/HTML/CSV pipeline (`analytics.py`, `frontend_csv_builder.py`, `html_generator.py`, `price_alerter.py`) which form an allowed dependency chain. Every public function has type hints and a docstring. Pure functions stay in `src/`, while side effects (DB writes, HTTP calls, sleeps) are orchestrated in `scripts/`.

**Exception:** `src/browser_fetcher.py` imports from `src/flight_fetcher.py` (for `BotChallengeError`, `NetworkError`, `RateLimitedError`) and from `src/proxy_manager.py`. This is the only permitted cross-import outside the analytics chain.

## Transport Layer: Browser Automation

Scraping is done via a **real Chromium browser** (Playwright), not a raw HTTP client. `src/browser_fetcher.py` owns all of this. It is the only file that touches Playwright.

### How it works

`install_browser_patch()` is called once at startup. It:
1. Loads proxies from `data/proxies.txt` (format: `host:port:username:password`, one per line).
2. Creates two persistent browser contexts — `_context_direct` and `_context_proxy` — backed by profile directories at `data/browser_profiles/direct` and `data/browser_profiles/proxy`. Persistent profiles mean cookies and localStorage survive across scrape runs.
3. Injects `_STEALTH_SCRIPT` into every new page via `add_init_script`. This runs before any page JS and patches all major bot-detection vectors (see below).
4. Monkey-patches `fast_flights.core.fetch` with `browser_fetch`.

Each call to `browser_fetch(params)`:
1. Decides routing: **50 % direct / 50 % proxy** (configurable via `PROXY_SPLIT_RATIO`).
2. Opens a new page in the chosen context, navigates to the Google Flights URL, waits for `domcontentloaded`.
3. Waits for `networkidle` (non-fatal timeout).
4. Applies a random human **dwell time** (`PLAYWRIGHT_DWELL_MIN_MS`–`PLAYWRIGHT_DWELL_MAX_MS`) and a random **mouse move** to simulate reading.
5. Extracts `page.content()`, closes the page, returns a `BrowserResponse`.

### Anti-bot detection measures

All measures are active for **both** contexts (direct and proxy):

| Layer | Mechanism |
|---|---|
| Chrome flag | `--disable-blink-features=AutomationControlled` — removes the C++-level `navigator.webdriver` flag |
| Chrome flag | `--disable-quic` — prevents Chrome from trying QUIC/HTTP3 (UDP, cannot be tunnelled through a proxy, causes hangs) |
| JS stealth script | Removes `navigator.webdriver`, fakes `window.chrome`, populates `navigator.plugins` / `mimeTypes`, fixes `navigator.languages`, patches `Permissions.query` for notifications, patches WebGL vendor/renderer strings to "Intel Inc." / "Intel Iris OpenGL Engine", sets `hardwareConcurrency=8` / `deviceMemory=8`, fixes `outerWidth`/`outerHeight` to be non-zero |
| Realistic UA | `config.PLAYWRIGHT_USER_AGENT` — real Chrome 131 on Linux |
| Client-hint headers | `sec-ch-ua`, `sec-ch-ua-mobile`, `sec-ch-ua-platform` in `config.PLAYWRIGHT_EXTRA_HEADERS` |
| Viewport pool | Five realistic resolutions, picked at random per context creation |
| Consent cookie | `SOCS=CAI` pre-seeded on `.google.com` to bypass the EU consent wall without triggering a redirect |
| Human dwell | 1.2–3.5 s random wait after `networkidle` before reading the DOM |
| Mouse movement | Random move within the viewport after dwell |
| Request pacing | `request_pacer.py` spaces all requests across the 06:00–22:00 window with ±10 % jitter |

### Proxy setup

The project runs a private **Squid proxy** on a second home ISP connection (`86.90.97.144:3128`). This gives scrapes an alternative exit IP without any paid proxy service.

**Critical:** Playwright (Chrome on Windows) does not respond to Squid's `407 Proxy Auth Required` challenge when starting from a fresh profile — Chrome on Windows resolves proxy credentials from Windows Credential Manager, which a fresh Playwright profile doesn't have. The fix is **IP-based ACL in Squid** so Chrome never sees a 407:

```squid
# /etc/squid/squid.conf — on the Squid machine
acl scraper_ip src 84.31.85.131
http_access allow scraper_ip
```

Because of this, **do not add `username`/`password` to the Playwright proxy dict** — credentials in the proxy config would cause Chrome to send a `Proxy-Authorization` header that Squid rejects before the IP-based allow rule fires.

The proxy URL in `data/proxies.txt` still uses `host:port:user:pass` format (for documentation), but `browser_fetcher.py` only uses the host and port when building the Playwright proxy config.

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