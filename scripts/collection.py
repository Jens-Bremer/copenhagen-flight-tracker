from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from src.database import insert_observations
from src.flight_fetcher import fetch_flights_for_date
from src.response_parser import parse_flights

logger = logging.getLogger(__name__)


def execute_single_job(
    origin: str,
    destination: str,
    departure_date: date,
    db_path: str,
) -> tuple[int, Exception | None]:
    """Fetch, parse, and store flights for one job.

    Returns (rows_inserted, exception_or_none). Never raises — the caller
    decides how to handle failures. rows_inserted == 0 with exc == None
    means the fetch succeeded but produced no flights.
    """
    try:
        result = fetch_flights_for_date(
            origin, destination, departure_date, raise_on_failure=True
        )
        observations = parse_flights(
            result,
            origin,
            destination,
            departure_date,
            datetime.now(tz=timezone.utc),
        )
        inserted = insert_observations(db_path, observations)
        return inserted, None
    except Exception as exc:
        return 0, exc
