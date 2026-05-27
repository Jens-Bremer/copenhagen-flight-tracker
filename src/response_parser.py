"""Parse upstream fast-flights results into flat observation rows."""

import logging
import re
from datetime import date, datetime
from typing import Optional

import fast_flights

logger = logging.getLogger(__name__)

_CURRENCY_SYMBOLS = {
    "€": "EUR",
    "$": "USD",
    "£": "GBP",
    # Common European prefixes/symbols.
    # Note: "kr" is shared (DKK/NOK/SEK); we treat it as SEK as a rough default.
    "kr": "SEK",
    "Fr": "CHF",
    "zł": "PLN",
}

# Matches upstream fast-flights duration strings like "1h 25m", "55m", "2h".
# Either (or both) groups may be present; an empty match is rejected by the
# helper so plain whitespace or "" returns None instead of zero minutes.
_DURATION_RE = re.compile(r"^(?:(\d+)h)?\s*(?:(\d+)m)?$")


def _parse_duration_to_minutes(duration: Optional[str]) -> Optional[int]:
    """Parse an upstream duration string ("1h 25m", "55m", "2h") to minutes.

    Returns None for missing input, empty/whitespace strings, or anything that
    doesn't match the ``[Nh][ Nm]`` shape. Never raises — the fast-flights
    upstream format is not under our control, so callers must be tolerant.
    """
    if duration is None:
        return None
    stripped = duration.strip()
    if not stripped:
        return None
    match = _DURATION_RE.match(stripped)
    if not match:
        return None
    hours_str, minutes_str = match.group(1), match.group(2)
    # Reject "" / pure-whitespace matches where neither group fired.
    if hours_str is None and minutes_str is None:
        return None
    hours = int(hours_str) if hours_str is not None else 0
    minutes = int(minutes_str) if minutes_str is not None else 0
    return hours * 60 + minutes


def extract_price_parts(raw_price: Optional[str]) -> tuple:
    """Parse a raw price string (e.g. '€89') into (amount_in_cents, currency_code).

    Returns (None, None) if the price is missing or uses an unknown symbol.
    """
    if not raw_price:
        return (None, None)

    currency = None
    # Some currencies are presented as multi-character prefixes (e.g. "kr", "Fr").
    for prefix, code in _CURRENCY_SYMBOLS.items():
        if raw_price.startswith(prefix):
            currency = code
            break
    if not currency:
        logger.warning("Unknown currency symbol in price: %r", raw_price)
        return (None, None)
    match = re.search(r"[\d]+(?:\.\d+)?", raw_price)
    if not match:
        return (None, None)
    amount_cents = round(float(match.group()) * 100)
    return (amount_cents, currency)


def parse_flights(
    result: Optional[fast_flights.Result],
    origin: str,
    destination: str,
    departure_date: date,
    retrieved_at: datetime,
) -> list:
    """Convert a fast-flights Result into a list of flat observation dicts."""
    if result is None:
        return []
    rows = []
    seen: set = set()
    for flight in result.flights:
        # Google Flights often surfaces the same flight twice — once as the
        # "best" pick and again in the main list. Skip exact duplicates so a
        # single scrape never inserts two rows for the same physical flight.
        key = (flight.name, flight.departure, flight.arrival)
        if key in seen:
            continue
        seen.add(key)
        price_amount, price_currency = extract_price_parts(flight.price)
        rows.append(
            {
                "retrieved_at": retrieved_at.isoformat(),
                "departure_date": departure_date.strftime("%Y-%m-%d"),
                "origin": origin,
                "destination": destination,
                "airline": flight.name,
                "departure_time": flight.departure,
                "arrival_time": flight.arrival,
                "duration": flight.duration,
                "duration_minutes": _parse_duration_to_minutes(flight.duration),
                "stops": flight.stops,
                "price": flight.price,
                "price_amount": price_amount,
                "price_currency": price_currency,
                "is_best": flight.is_best,
                "current_price_trend": result.current_price,
            }
        )
    return rows
