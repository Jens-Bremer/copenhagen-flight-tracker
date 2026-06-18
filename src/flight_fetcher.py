"""Transport layer for fetching Google Flights pages via fast-flights.

This module defines a small error hierarchy used by the scheduler/health checks.
The HTTP transport layer uses browser automation (Playwright) via browser_fetcher.py.
"""

import logging
from datetime import date
from typing import Optional

import fast_flights

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
    except RuntimeError as exc:
        # fast_flights raises RuntimeError("No flights found: <html>…") when its
        # CSS selectors find nothing. Reclassify as ParseError so _classify_failure
        # reports "parse_error" instead of "other", and the log line stays concise.
        wrapped = ParseError(str(exc)) if "No flights found" in str(exc) else exc
        if raise_on_failure:
            raise wrapped from exc
        logger.error(
            "Failed to fetch %s→%s on %s: %s",
            origin, destination, departure_date, wrapped,
        )
        return None
    except Exception as exc:
        if raise_on_failure:
            raise
        logger.error(
            "Failed to fetch %s→%s on %s: %s", origin, destination, departure_date, exc
        )
        return None
