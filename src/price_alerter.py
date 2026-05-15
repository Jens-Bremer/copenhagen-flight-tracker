import logging
import sqlite3
from datetime import date
from typing import Optional

from src.analytics import compute_price_percentile, format_ordinal
from src.notifier import send_alert

logger = logging.getLogger(__name__)


def find_cheap_flights(
    db_path: str, threshold: int, run_date: Optional[str] = None
) -> list:
    """Return today's observed flights where price_amount <= threshold, ordered by price."""
    if run_date is None:
        run_date = date.today().isoformat()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT origin, destination, departure_date, airline,
                   departure_time, price_amount, price_currency
            FROM flight_observations
            WHERE retrieved_at LIKE ?
              AND price_amount IS NOT NULL
              AND price_amount <= ?
            ORDER BY price_amount ASC
            """,
            (f"{run_date}%", threshold),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def format_alert_message(
    flights: list, threshold: int, db_path: Optional[str] = None
) -> str:
    """Format a concise ntfy message summarising cheap flights."""
    threshold_euros = threshold // 100
    lines = [f"{len(flights)} cheap flight(s) found (≤€{threshold_euros}):"]
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
            f"  {f['airline']}  {f['departure_time']}  {amount} {currency}{percentile_text}"
        )
    return "\n".join(lines)


def check_and_alert_cheap_flights(
    db_path: str,
    threshold: int,
    run_date: Optional[str] = None,
) -> bool:
    """Find cheap flights and send an alert if any exist. Returns True if alert was sent."""
    flights = find_cheap_flights(db_path, threshold, run_date)
    if not flights:
        logger.info("No flights below threshold (%d cents) today", threshold)
        return False
    message = format_alert_message(flights, threshold, db_path=db_path)
    logger.info("Found %d cheap flight(s) — sending alert", len(flights))
    send_alert(
        title=f"{len(flights)} flight(s) under €{threshold // 100}",
        message=message,
        priority="default",
    )
    return True
