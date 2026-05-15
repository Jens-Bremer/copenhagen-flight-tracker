import bisect
import sqlite3
from typing import Optional


def compute_price_percentile(
    db_path: str,
    origin: str,
    destination: str,
    departure_date: str,
    price_amount: int,
) -> Optional[float]:
    """Return percentile rank for a price on a specific route+departure_date."""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT price_amount
            FROM flight_observations
            WHERE origin = ?
              AND destination = ?
              AND departure_date = ?
              AND price_amount IS NOT NULL
            ORDER BY price_amount ASC
            """,
            (origin, destination, departure_date),
        ).fetchall()
    finally:
        conn.close()

    prices = [row[0] for row in rows]
    if len(prices) < 5:
        return None

    if len(prices) == 1:
        return 0.0

    index = bisect.bisect_left(prices, price_amount)
    if index <= 0:
        return 0.0
    if index >= len(prices) - 1:
        return 100.0
    return (index / (len(prices) - 1)) * 100.0
