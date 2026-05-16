import logging
import sqlite3
from datetime import date
from typing import Optional, Union

from src.analytics import compute_price_percentile, format_ordinal
from src.notifier import send_alert

logger = logging.getLogger(__name__)

_THRESHOLD_TYPE = Union[int, dict]

_SELECT_COLS = """
    SELECT origin, destination, departure_date, airline,
           departure_time, price_amount, price_currency
    FROM flight_observations
    WHERE retrieved_at LIKE ?
      AND price_amount IS NOT NULL
"""


def _route_threshold(threshold: dict, origin: str, destination: str) -> int:
    return threshold.get((origin, destination), threshold["_default"])


def find_cheap_flights(
    db_path: str, threshold: _THRESHOLD_TYPE, run_date: Optional[str] = None
) -> list:
    """Return flights with price_amount <= threshold, ordered by ascending price."""
    if run_date is None:
        run_date = date.today().isoformat()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        if isinstance(threshold, int):
            rows = conn.execute(
                _SELECT_COLS + "  AND price_amount <= ?\nORDER BY price_amount ASC",
                (f"{run_date}%", threshold),
            ).fetchall()
        else:
            all_rows = conn.execute(
                _SELECT_COLS + "ORDER BY price_amount ASC",
                (f"{run_date}%",),
            ).fetchall()
            rows = [
                r
                for r in all_rows
                if r["price_amount"]
                <= _route_threshold(threshold, r["origin"], r["destination"])
            ]
        return [dict(row) for row in rows]
    finally:
        conn.close()


def format_alert_message(
    flights: list, threshold: _THRESHOLD_TYPE, db_path: Optional[str] = None
) -> str:
    """Format a concise ntfy message summarising cheap flights."""
    if isinstance(threshold, int):
        header = f"{len(flights)} cheap flight(s) found (≤€{threshold // 100}):"
    else:
        header = f"{len(flights)} cheap flight(s) found (per-route thresholds):"
    lines = [header]
    for f in flights:
        amount = f["price_amount"] // 100
        currency = f.get("price_currency") or ""
        percentile_text = ""
        if db_path and f.get("price_amount") is not None:
            percentile = compute_price_percentile(
                db_path=db_path,
                origin=f["origin"],
                destination=f["destination"],
                departure_date=f["departure_date"],
                price_amount=f["price_amount"],
            )
            if percentile is not None:
                rounded = round(percentile)
                percentile_text = f" ({format_ordinal(rounded)} percentile"
                if rounded <= 10:
                    percentile_text += " — historically very cheap"
                percentile_text += ")"
        lines.append(
            f"  {f['origin']}→{f['destination']}  {f['departure_date']}"
            f"  {f['airline']}  {f['departure_time']}"
            f"  {amount} {currency}{percentile_text}"
        )
    return "\n".join(lines)


def check_and_alert_cheap_flights(
    db_path: str,
    threshold: _THRESHOLD_TYPE,
    run_date: Optional[str] = None,
) -> bool:
    """Find cheap flights and send an alert if any exist.

    Returns True if alert was sent.
    """
    flights = find_cheap_flights(db_path, threshold, run_date)
    if not flights:
        logger.info("No flights below threshold today")
        return False
    message = format_alert_message(flights, threshold, db_path=db_path)
    logger.info("Found %d cheap flight(s) — sending alert", len(flights))
    if isinstance(threshold, int):
        title = f"{len(flights)} flight(s) under €{threshold // 100}"
    else:
        title = f"{len(flights)} cheap flight(s) found"
    send_alert(title=title, message=message, priority="default")
    return True
