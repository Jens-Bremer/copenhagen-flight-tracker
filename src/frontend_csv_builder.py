"""Derivative CSV builder: turn data/flights_export.csv into a slim, normalised
flights_frontend.csv for browser ingestion. See docs/superpowers/plans/
2026-05-15-frontend-csv-builder.md and issue #55 for the full contract.

This module imports only stdlib + config per the project module contract
(CLAUDE.md). Side effects live in the orchestrator `build()` and the CLI
wrapper in scripts/build_frontend_csv.py.
"""

from datetime import datetime, timezone


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
