"""Per (route, airline, days_before) price volatility (stdev + CV).

Pure builder. See docs/INSIGHTS_CONTRACT.md for the JSON-blob schema.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date as date_type, datetime, timezone
from typing import Any, Iterable

from src.insights.stats import coefficient_of_variation

MIN_SAMPLES = 3


def _route(row: dict[str, Any]) -> str:
    return f"{row['origin']}-{row['destination']}"


def _days_before(row: dict[str, Any]) -> int | None:
    try:
        dep = date_type.fromisoformat(row["departure_date"])
    except (KeyError, ValueError):
        return None
    db = (dep - row["retrieved_at"].date()).days
    return db if db >= 0 else None


def build_volatility(
    rows: Iterable[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Per-bucket stdev (cents) + coefficient of variation."""
    grouped: dict[tuple[str, str, int], list[int]] = defaultdict(list)
    for row in rows:
        db = _days_before(row)
        if db is None:
            continue
        grouped[(_route(row), row["airline"], db)].append(int(row["price_cents"]))

    buckets: list[dict[str, Any]] = []
    for (route, airline, db), prices in grouped.items():
        if len(prices) < MIN_SAMPLES:
            continue
        std_cents = int(round(statistics.stdev(prices)))
        cv = coefficient_of_variation(prices)
        buckets.append(
            {
                "route": route,
                "airline": airline,
                "days_before": db,
                "n": len(prices),
                "std_cents": std_cents,
                "cv": None if cv is None else round(cv, 4),
            }
        )

    buckets.sort(key=lambda b: (b["route"], b["airline"], -b["days_before"]))
    return {
        "generated_at": (now or datetime.now(timezone.utc))
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "buckets": buckets,
    }
