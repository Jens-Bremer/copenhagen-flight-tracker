import bisect
import sqlite3
from typing import Optional


def format_ordinal(n: int) -> str:
    """Return the ordinal representation for an integer."""
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def compute_price_percentile(
    db_path: str,
    origin: str,
    destination: str,
    departure_date: str,
    price_amount: int,
) -> Optional[float]:
    """Return percentile rank for a price on a specific route+departure_date.

    Ties are ranked using the midpoint of the tied range so duplicate prices
    share the same percentile instead of being split across multiple ranks.
    """
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

    if price_amount <= prices[0]:
        return 0.0
    if price_amount >= prices[-1]:
        return 100.0

    lower_index = bisect.bisect_left(prices, price_amount)
    upper_index = bisect.bisect_right(prices, price_amount)
    rank = lower_index
    if upper_index > lower_index:
        # Use the midpoint between first and last tied positions.
        rank = (lower_index + upper_index - 1) / 2
    return (rank / (len(prices) - 1)) * 100.0
