"""Derivative CSV builder: turn data/flights_export.csv into a slim, normalised
flights_frontend.csv for browser ingestion. See docs/superpowers/plans/
2026-05-15-frontend-csv-builder.md and issue #55 for the full contract.

This module imports only stdlib + config per the project module contract
(CLAUDE.md). Side effects live in the orchestrator `build()` and the CLI
wrapper in scripts/build_frontend_csv.py.
"""

import re
from datetime import datetime, timezone
from typing import Optional

_TIME_PROSE_RE = re.compile(
    r"^\s*(?P<hour>\d{1,2}):(?P<minute>\d{2})\s*(?P<meridiem>AM|PM)\b",
    re.IGNORECASE,
)

_MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}

_PROSE_DATETIME_RE = re.compile(
    r"^\s*(?P<hour>\d{1,2}):(?P<minute>\d{2})\s*(?P<meridiem>AM|PM)"
    r"\s+on\s+\w{3},\s*(?P<month>\w{3})\s+(?P<day>\d{1,2})\s*$",
    re.IGNORECASE,
)


def parse_retrieved_at(raw: str) -> datetime:
    """Parse strict ISO 8601 with offset; return tz-aware UTC, minute resolution.

    Drops seconds and microseconds (floor). Raises ValueError on missing offset
    or unparseable input.
    """
    if not raw:
        raise ValueError("retrieved_at is empty")
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        raise ValueError(f"retrieved_at missing tz offset: {raw!r}")
    parsed = parsed.astimezone(timezone.utc)
    return parsed.replace(second=0, microsecond=0)


def parse_time_of_day(prose: str) -> tuple:
    """Extract (hour_24, minute) from prose like '7:30 PM on Fri, Jun 19'.

    Locale-independent: relies only on H:MM AM/PM. Empty string and unparseable
    inputs raise ValueError; the caller is expected to catch and drop the row.
    """
    if not prose:
        raise ValueError("time prose is empty")
    match = _TIME_PROSE_RE.match(prose)
    if not match:
        raise ValueError(f"unparseable time prose: {prose!r}")
    hour = int(match.group("hour"))
    minute = int(match.group("minute"))
    if not (1 <= hour <= 12) or not (0 <= minute <= 59):
        raise ValueError(f"time out of range: {prose!r}")
    meridiem = match.group("meridiem").upper()
    if meridiem == "AM":
        hour_24 = 0 if hour == 12 else hour
    else:
        hour_24 = 12 if hour == 12 else hour + 12
    return (hour_24, minute)


def parse_prose_datetime(prose: str, year: int) -> datetime:
    """Parse '9:45 AM on Sat, Jun 20' + year -> datetime(2026, 6, 20, 9, 45).

    Naive (no tzinfo) — output represents local time at the relevant airport.
    Year is supplied externally because the prose omits it. Empty input or
    any unparseable component raises ValueError; the caller drops the row.
    """
    if not prose:
        raise ValueError("prose datetime is empty")
    match = _PROSE_DATETIME_RE.match(prose)
    if not match:
        raise ValueError(f"unparseable prose datetime: {prose!r}")
    hour = int(match.group("hour"))
    minute = int(match.group("minute"))
    if not (1 <= hour <= 12) or not (0 <= minute <= 59):
        raise ValueError(f"time out of range: {prose!r}")
    meridiem = match.group("meridiem").upper()
    if meridiem == "AM":
        hour_24 = 0 if hour == 12 else hour
    else:
        hour_24 = 12 if hour == 12 else hour + 12
    month_key = match.group("month").title()
    if month_key not in _MONTHS:
        raise ValueError(f"unknown month in prose: {prose!r}")
    month = _MONTHS[month_key]
    day = int(match.group("day"))
    return datetime(year, month, day, hour_24, minute)


def compute_duration_minutes(dep: datetime, arr: datetime) -> int:
    """Return integer minutes between dep and arr (truncated). Negative and
    zero results are passed through unchanged; the caller (slim_row) treats
    non-positive durations as parse failures and drops the row."""
    return int((arr - dep).total_seconds() // 60)


def _format_retrieved_at(dt: datetime) -> str:
    """Format a UTC, minute-resolution datetime as '2026-05-15T13:45Z'.

    Python 3.9's datetime.isoformat() emits '+00:00' rather than 'Z'; using
    strftime here pins the contract regardless of Python version.
    """
    return dt.strftime("%Y-%m-%dT%H:%MZ")


def slim_row(raw_row: dict) -> Optional[dict]:
    """Per-row transform. Returns the 10-column output dict, or None if the
    row should be skipped (parse failure or intentional drop).

    Returning None instead of raising lets the orchestrator own row numbering
    and warning emission; this function stays pure and easy to unit test.
    """
    departure_time = raw_row.get("departure_time", "")
    arrival_time = raw_row.get("arrival_time", "")
    if not departure_time or not arrival_time:
        return None

    raw_price = raw_row.get("price_amount", "")
    try:
        price_cents = int(raw_price)
    except (TypeError, ValueError):
        return None
    if price_cents <= 0:
        return None

    try:
        retrieved_at = parse_retrieved_at(raw_row["retrieved_at"])
        departure_date = datetime.strptime(
            raw_row["departure_date"], "%Y-%m-%d"
        ).date()
        dep_h, dep_m = parse_time_of_day(departure_time)
        departure_at = datetime(
            departure_date.year,
            departure_date.month,
            departure_date.day,
            dep_h,
            dep_m,
        )
        arrival_at = parse_prose_datetime(arrival_time, departure_date.year)
    except (KeyError, ValueError):
        return None

    # Cross-year rollover: prose omits the year, so if arrival ends up before
    # departure (e.g. dep Dec 31, arr "Jan 1"), bump arrival by one year.
    if arrival_at < departure_at:
        try:
            arrival_at = arrival_at.replace(year=arrival_at.year + 1)
        except ValueError:
            return None

    duration = compute_duration_minutes(departure_at, arrival_at)
    if duration <= 0:
        return None

    return {
        "retrieved_at": _format_retrieved_at(retrieved_at),
        "departure_date": raw_row["departure_date"],
        "origin": raw_row["origin"],
        "destination": raw_row["destination"],
        "airline": raw_row.get("airline", ""),
        "departure_at": departure_at.isoformat(timespec="seconds"),
        "arrival_at": arrival_at.isoformat(timespec="seconds"),
        "duration_minutes": duration,
        "price_cents": price_cents,
        "price_currency": raw_row.get("price_currency", ""),
    }


def sort_rows(rows: list) -> list:
    """Stable sort by (departure_date, origin, destination, retrieved_at,
    price_cents, airline). The trailing airline tiebreaker pins output
    determinism when otherwise-identical observations differ only by carrier.
    """
    return sorted(
        rows,
        key=lambda r: (
            r["departure_date"],
            r["origin"],
            r["destination"],
            r["retrieved_at"],
            r["price_cents"],
            r["airline"],
        ),
    )
