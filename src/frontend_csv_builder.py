"""Derivative CSV builder: turn data/flights_export.csv into a slim, normalised
flights_frontend.csv for browser ingestion. See docs/superpowers/plans/
2026-05-15-frontend-csv-builder.md and issue #55 for the full contract.

This module imports only stdlib + config per the project module contract
(CLAUDE.md). Side effects live in the orchestrator `build()` and the CLI
wrapper in scripts/build_frontend_csv.py.
"""

import re
from datetime import datetime, timezone

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
