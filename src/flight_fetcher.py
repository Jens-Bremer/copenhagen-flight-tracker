import logging
from datetime import date
from typing import Optional

import fast_flights
import fast_flights.core
from primp import Client

import config


# --- Exception hierarchy (issue #111) ---
#
# Classify fetch failures so the scheduler's heartbeat (and downstream health
# checks) can distinguish a transient network blip from a structural Google
# block. BotChallengeError + RateLimitedError together form the LEADING ban
# indicator the project's #1 risk requires.
class FlightFetchError(Exception):
    """Base class for any error raised inside the patched fetch path."""


class BotChallengeError(FlightFetchError):
    """Response looks like a consent/captcha/anti-bot interstitial.

    Detected via raw byte floor (response shorter than expected) or by a
    case-insensitive substring match against config.BOT_CHALLENGE_TITLE_PATTERNS.
    """


class RateLimitedError(FlightFetchError):
    """Google returned an HTTP 429 or 403 — explicit rate-limit / block."""


class ParseError(FlightFetchError):
    """fast_flights got a response but could not extract structured data."""


class NetworkError(FlightFetchError):
    """primp raised a connection/timeout error — no usable response."""


# Patch fast_flights to avoid Google's EU cookie consent wall
def patched_fetch(params: dict):
    # verify=False is intentional: primp manages its own TLS/browser fingerprint stack.
    # Python's default cert verification can conflict with that.
    client = Client(impersonate=config.IMPERSONATION, verify=False)
    # The SOCS=CAI cookie signals that the user has accepted/rejected cookies,
    # preventing the consent redirect.
    try:
        res = client.get(
            "https://www.google.com/travel/flights",
            params=params,
            headers={"Cookie": "SOCS=CAI; CONSENT=PENDING+999"},
        )
    except (ConnectionError, TimeoutError) as exc:
        # primp surfaces transport failures as the standard built-in
        # ConnectionError / TimeoutError. Wrap them so callers can branch
        # on NetworkError without depending on primp's internals.
        raise NetworkError(str(exc)) from exc

    if res.status_code in (429, 403):
        raise RateLimitedError(f"HTTP {res.status_code}")
    if res.status_code != 200:
        raise RuntimeError(f"HTTP {res.status_code}: {res.text_markdown}")

    # --- Bot-challenge detection (raw byte floor + title substring) ---
    # Cheap, deterministic, no DB state. A genuine Google Flights HTML page
    # is tens to hundreds of kilobytes; consent / captcha interstitials are
    # typically a few KB. The substring scan catches the slightly-larger
    # consent screens that slip above the byte floor.
    body = getattr(res, "text", "") or ""
    if len(body.encode("utf-8")) < config.BOT_CHALLENGE_MIN_BYTES:
        raise BotChallengeError("response below minimum length")
    lower_body = body.lower()
    for pattern in config.BOT_CHALLENGE_TITLE_PATTERNS:
        if pattern.lower() in lower_body:
            raise BotChallengeError(f"detected pattern: {pattern}")

    return res


def install_fetch_patch() -> None:
    """Install the patched fetch onto fast_flights.core.

    Must be called once at process startup (run_daily.main / run_scheduler.main).
    Tests that need the unpatched fast_flights.core.fetch can simply not call this.

    Probes the configured impersonation profile up-front. primp emits only a
    WARNING when the profile is missing and silently switches to 'random' —
    which serves Google a different TLS fingerprint per request and gets the
    scraper bot-walled. We promote that warning into a fatal RuntimeError so
    a misconfiguration is impossible to ignore. See config.IMPERSONATION for
    the rationale and valid candidates.
    """
    try:
        Client(impersonate=config.IMPERSONATION, verify=False)
    except Exception as exc:
        raise RuntimeError(
            f"primp impersonation profile {config.IMPERSONATION!r} is not "
            f"available in the installed primp version ({exc}). primp must be "
            "pinned (pyproject.toml) to a release that ships this profile, "
            "OR config.IMPERSONATION must be updated to a profile that "
            "exists. Do NOT proceed with scraping — the silent 'random' "
            "fallback will get you bot-walled."
        ) from exc
    fast_flights.core.fetch = patched_fetch


logger = logging.getLogger(__name__)


def fetch_flights_for_date(
    origin: str,
    destination: str,
    departure_date: date,
    raise_on_failure: bool = False,
) -> Optional[fast_flights.Result]:
    """Fetch one-way flights for a single route and date.

    Returns None on failure unless raise_on_failure is True.

    When raise_on_failure is True, FlightFetchError subclasses (and any other
    exception raised by fast_flights) propagate unchanged so the orchestrator
    can classify failures into per-category counters.
    """
    logger.info(
        "Querying %s→%s on %s",
        origin,
        destination,
        departure_date.strftime("%Y-%m-%d"),
    )
    try:
        return fast_flights.get_flights(
            flight_data=[
                fast_flights.FlightData(
                    date=departure_date.strftime("%Y-%m-%d"),
                    from_airport=origin,
                    to_airport=destination,
                )
            ],
            trip=config.TRIP_TYPE,
            passengers=fast_flights.Passengers(adults=config.PASSENGERS_ADULTS),
            seat=config.SEAT_CLASS,
            fetch_mode="common",
            max_stops=config.MAX_STOPS,
        )
    except Exception as exc:
        if raise_on_failure:
            raise
        logger.error(
            "Failed to fetch %s→%s on %s: %s", origin, destination, departure_date, exc
        )
        return None
