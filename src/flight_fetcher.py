import logging
from datetime import date
from typing import Optional

import fast_flights
import fast_flights.core
from primp import Client

import config


# Patch fast_flights to avoid Google's EU cookie consent wall
def patched_fetch(params: dict):
    client = Client(impersonate="chrome_126", verify=False)
    # The SOCS=CAI cookie signals that the user has accepted/rejected cookies,
    # preventing the consent redirect.
    res = client.get(
        "https://www.google.com/travel/flights",
        params=params,
        headers={"Cookie": "SOCS=CAI; CONSENT=PENDING+999"},
    )
    assert res.status_code == 200, f"{res.status_code} Result: {res.text_markdown}"
    return res


fast_flights.core.fetch = patched_fetch

logger = logging.getLogger(__name__)


def fetch_flights_for_date(
    origin: str,
    destination: str,
    departure_date: date,
) -> Optional[fast_flights.Result]:
    """Fetch one-way flights for a single route and date. Returns None on failure."""
    logger.info(
        "Querying %s→%s on %s", origin, destination, departure_date.strftime("%Y-%m-%d")
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
        logger.error(
            "Failed to fetch %s→%s on %s: %s", origin, destination, departure_date, exc
        )
        return None
