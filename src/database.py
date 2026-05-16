import os
import sqlite3
from typing import Optional

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS flight_observations (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    retrieved_at        TEXT    NOT NULL,
    departure_date      TEXT    NOT NULL,
    origin              TEXT    NOT NULL,
    destination         TEXT    NOT NULL,
    airline             TEXT    NOT NULL,
    departure_time      TEXT    NOT NULL,
    arrival_time        TEXT    NOT NULL,
    duration            TEXT    NOT NULL,
    stops               INTEGER NOT NULL,
    price               TEXT,
    price_amount        INTEGER,
    price_currency      TEXT,
    is_best             INTEGER NOT NULL,
    current_price_trend TEXT
);
"""

_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_flight_lookup
ON flight_observations (origin, destination, departure_date, airline, departure_time);
"""

_INSERT = """
INSERT INTO flight_observations (
    retrieved_at, departure_date, origin, destination, airline,
    departure_time, arrival_time, duration, stops, price,
    price_amount, price_currency, is_best, current_price_trend
) VALUES (
    :retrieved_at, :departure_date, :origin, :destination, :airline,
    :departure_time, :arrival_time, :duration, :stops, :price,
    :price_amount, :price_currency, :is_best, :current_price_trend
);
"""


def initialize_database(db_path: str) -> None:
    """Create the database file and schema. Safe to call multiple times."""
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(_CREATE_TABLE)
        conn.execute(_CREATE_INDEX)
        conn.commit()
    finally:
        conn.close()


def insert_observations(db_path: str, observations: list) -> int:
    """Insert a batch of observation dicts in a single transaction.

    Returns row count inserted.
    """
    if not observations:
        return 0
    conn = sqlite3.connect(db_path)
    try:
        conn.executemany(_INSERT, observations)
        conn.commit()
        return len(observations)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def query_price_history(
    db_path: str,
    departure_date: str,
    origin: Optional[str] = None,
    destination: Optional[str] = None,
    airline: Optional[str] = None,
) -> list:
    """Return observations for a departure date, ordered by retrieved_at ascending."""
    sql = "SELECT * FROM flight_observations WHERE departure_date = ?"
    params: list = [departure_date]
    if origin:
        sql += " AND origin = ?"
        params.append(origin)
    if destination:
        sql += " AND destination = ?"
        params.append(destination)
    if airline:
        sql += " AND airline = ?"
        params.append(airline)
    sql += " ORDER BY retrieved_at ASC"

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
