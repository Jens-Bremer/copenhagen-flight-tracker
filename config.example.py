# config.py — single source of truth for all tuneable parameters
#
# TEMPLATE FILE: Copy this to config.py and edit the placeholders for your setup.
# config.py itself is gitignored so you can safely edit it in place without
# blocking git pull updates.

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
NTFY_TOPIC = "your-ntfy-topic-here"  # change to a random unguessable string
NTFY_URL = "https://ntfy.sh"
PRICE_ALERT_THRESHOLD = {
    ("CPH", "AMS"): 5000,  # €50
    ("AMS", "CPH"): 7500,  # €75
    "_default": 6000,  # €60 for any unlisted route
}

# --- Frontend CSV ---
FRONTEND_MAX_DURATION_MINUTES = 120

# --- Stale-flight threshold ---
# Flights whose most recent observation is older than this many days are
# visually flagged in the dashboard as potentially outdated.
STALE_FLIGHT_DAYS: int = 3

# --- Logging ---
LOG_DIR = "logs"
LOG_KEEP_DAYS = 14

# --- Ban / rate-limit signals (issue #111) ---
BOT_CHALLENGE_MIN_BYTES = 10000
BOT_CHALLENGE_TITLE_PATTERNS = [
    "consent",
    "captcha",
    "unusual traffic",
    "are you a robot",
]
CONSECUTIVE_FAILURE_DAYS = 2

# --- Sweet-spot recommendation (issue #113) ---
RELIABLE_MIN_OBSERVATIONS = 10

# --- Proxy rotation ---
PROXY_LIST_PATH = "data/proxies.txt"  # One proxy per line: host:port:username:password
PROXY_ENABLED = True  # Set False to scrape without proxies (uses your own IP)

# --- Browser automation (Playwright) ---
# headless=False runs a visible Chrome window — the right default for the
# dedicated home-PC deployment where a display is always available.
PLAYWRIGHT_HEADLESS = False
PLAYWRIGHT_BROWSER = "chromium"  # "chromium", "firefox", or "webkit"
# page-load timeout (ms); 60 s to cover proxy 407 round-trip + TLS + page load
PLAYWRIGHT_TIMEOUT_MS = 60000
PROXY_SPLIT_RATIO = 0.5  # Fraction of requests routed via proxy (0.0–1.0)

# Persistent profile directories for the two browser contexts.
# Playwright creates them on first launch; subsequent runs reuse cookies/localStorage.
PLAYWRIGHT_PROFILE_DIRECT = "data/browser_profiles/direct"
PLAYWRIGHT_PROFILE_PROXY = "data/browser_profiles/proxy"

# Realistic Chrome UA for Linux server. Keep in sync with sec-ch-ua header below.
PLAYWRIGHT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Client-hint headers that real Chrome always sends. Keep version numbers in
# sync with PLAYWRIGHT_USER_AGENT above.
PLAYWRIGHT_EXTRA_HEADERS = {
    "Accept-Language": "en-US,en;q=0.9",
    "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Linux"',
}

# Realistic viewport pool — pick one at random per context creation.
PLAYWRIGHT_VIEWPORT_POOL = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 1536, "height": 864},
    {"width": 1280, "height": 800},
]

# Post-navigation human dwell time range (ms). Browser waits a random amount
# in this range after the page settles before extracting content.
PLAYWRIGHT_DWELL_MIN_MS = 1200
PLAYWRIGHT_DWELL_MAX_MS = 3500

# networkidle timeout (ms). Playwright waits for no network requests for 500 ms
# within this budget after domcontentloaded. Increase if Flights loads slowly.
PLAYWRIGHT_NETWORKIDLE_TIMEOUT_MS = 15000
