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
