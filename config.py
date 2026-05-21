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
MAX_STOPS = 0  # 0 = nonstop only

# primp impersonation profile used by patched_fetch. MUST exist in the installed
# primp version — when it doesn't, primp silently picks a random profile, which
# gives every request a different TLS fingerprint and gets the scraper flagged
# as a bot. If you ever upgrade primp and need to change this, valid candidates
# at the time of writing: chrome_120, chrome_124, chrome_126-131, chrome_133,
# firefox_133, firefox_135. install_fetch_patch() probes the profile at startup
# and raises a clear error if it's not available, so an unsafe fallback can
# never silently happen.
IMPERSONATION = "chrome_131"

# --- Pacing ---
DAILY_WINDOW_START_HOUR = 6  # Local server time, 06:00
DAILY_WINDOW_END_HOUR = 22  # Local server time, 22:00
MIN_REQUEST_INTERVAL_SECONDS = 120  # Floor on any computed sleep interval
FETCH_RETRY_DELAY_SECONDS = 60  # Wait before each retry in the two-pass retry

# --- Health checks ---
HEALTH_FAILURE_RATE_THRESHOLD = 0.25  # Alert if >25% of jobs fail
HEALTH_COUNT_DROP_THRESHOLD = 0.50  # Alert if today's count < 50% of 7-day average

# --- Storage ---
DATABASE_PATH = "data/flights.db"
BACKUP_DIR = "data/backups"
BACKUP_KEEP_LAST_N = 7

# --- Notifications (ntfy.sh) ---
NTFY_TOPIC = "copenhagen-flights-jensbremer"  # ntfy.sh topic name
NTFY_URL = "https://ntfy.sh"
PRICE_ALERT_THRESHOLD = {
    ("CPH", "AMS"): 5000,  # €50
    ("AMS", "CPH"): 4500,  # €45
    "_default": 6000,  # €60 for any unlisted route
}

# --- Frontend CSV ---
FRONTEND_MAX_DURATION_MINUTES = 120

# --- Logging ---
LOG_DIR = "logs"
LOG_KEEP_DAYS = 14

# --- Ban / rate-limit signals (issue #111) ---
BOT_CHALLENGE_MIN_BYTES = 10000
BOT_CHALLENGE_TITLE_PATTERNS = ["consent", "captcha", "unusual traffic", "are you a robot"]
CONSECUTIVE_FAILURE_DAYS = 2

# --- Sweet-spot recommendation (issue #113) ---
RELIABLE_MIN_OBSERVATIONS = 10

# --- Proxy rotation (Webshare free tier) ---
PROXY_LIST_PATH = "data/proxies.txt"  # One proxy per line: host:port:username:password
PROXY_ENABLED = True  # Set False to scrape without proxies (uses your own IP)

# --- Browser automation (Playwright) ---
# headless=False runs a visible Chrome window — the right default for the
# dedicated home-PC deployment where a display is always available.
PLAYWRIGHT_HEADLESS = False
PLAYWRIGHT_BROWSER = "chromium"   # "chromium", "firefox", or "webkit"
PLAYWRIGHT_TIMEOUT_MS = 20000     # page-load timeout (ms)
PROXY_SPLIT_RATIO = 0.5            # Fraction of requests routed via proxy (0.0–1.0)
