import bisect
import sqlite3
from typing import Optional


def percentile_rank(
    price: int, sorted_prices: list[int], min_samples: int = 5
) -> Optional[float]:
    """Return midpoint-tie percentile rank of `price` in `sorted_prices`.

    Returns None when len(sorted_prices) < min_samples. Caller supplies
    the already-sorted prices. Edge cases: price <= prices[0] → 0.0;
    price >= prices[-1] → 100.0. Tied prices share the midpoint of
    their range.

    The defensive minimum-samples check also guards against the degenerate
    case of an empty list or a single-element list (where len - 1 = 0 would
    cause a division-by-zero in the rank normalisation). Both original
    implementations used n < 5 for this, so the default is preserved here.
    """
    n = len(sorted_prices)
    if n < min_samples:
        return None

    if price <= sorted_prices[0]:
        return 0.0
    if price >= sorted_prices[-1]:
        return 100.0

    lower_index = bisect.bisect_left(sorted_prices, price)
    upper_index = bisect.bisect_right(sorted_prices, price)
    rank: float = lower_index
    if upper_index > lower_index:
        # Use the midpoint between first and last tied positions.
        rank = (lower_index + upper_index - 1) / 2
    return (rank / (n - 1)) * 100.0


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
    return percentile_rank(price_amount, prices)
