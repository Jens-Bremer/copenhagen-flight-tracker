import logging
from datetime import date
from typing import Optional

import fast_flights

import config

logger = logging.getLogger(__name__)


def fetch_flights_for_date(
    origin: str,
    destination: str,
    departure_date: date,
) -> Optional[fast_flights.Result]:
    """Fetch one-way flights for a single route and date. Returns None on failure."""
    logger.info("Querying %s→%s on %s", origin, destination, departure_date.strftime("%Y-%m-%d"))
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
            fetch_mode="fallback",
        )
    except Exception as exc:
        logger.error("Failed to fetch %s→%s on %s: %s", origin, destination, departure_date, exc)
        return None
