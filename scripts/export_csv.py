import csv
import logging
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)

EXPORT_COLUMNS = [
    "retrieved_at",
    "departure_date",
    "origin",
    "destination",
    "airline",
    "departure_time",
    "arrival_time",
    "price_amount",
    "price_currency",
]


def export_to_csv(db_path: str, output_path: str) -> int:
    """Export flight_observations to a CSV file. Returns the number of rows written."""
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            f"SELECT {', '.join(EXPORT_COLUMNS)} FROM flight_observations"
            " ORDER BY retrieved_at DESC, departure_date ASC"
        ).fetchall()
    finally:
        conn.close()

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=EXPORT_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(row))

    logger.info("Exported %d rows to %s", len(rows), output_path)
    return len(rows)


if __name__ == "__main__":
    import config
    from src.log_config import setup_logging

    setup_logging()
    db = config.DATABASE_PATH
    out = os.path.join(os.path.dirname(os.path.abspath(db)), "flights_export.csv")
    count = export_to_csv(db, out)
    print(f"Exported {count} rows to {out}")
