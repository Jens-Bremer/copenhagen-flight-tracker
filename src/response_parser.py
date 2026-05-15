import re
import logging
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
    for flight in result.flights:
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
                "stops": flight.stops,
                "price": flight.price,
                "price_amount": price_amount,
                "price_currency": price_currency,
                "is_best": flight.is_best,
                "current_price_trend": result.current_price,
            }
        )
    return rows
