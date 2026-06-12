"""Per (route, airline, days_before) percentile verdict for the latest price.

Answers "is this price cheap / typical / expensive vs history" for the
freshest observation in each bucket. Pure; see docs/INSIGHTS_CONTRACT.md
for the JSON-blob schema.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date as date_type, datetime, timezone
from typing import Any, Iterable

from src.insights.stats import bucketed_percentile

MIN_SAMPLES = 3


def _route(row: dict[str, Any]) -> str:
    return f"{row['origin']}-{row['destination']}"


def _days_before(row: dict[str, Any]) -> int | None:
    try:
        dep_date = date_type.fromisoformat(row["departure_date"])
    except (KeyError, ValueError):
        return None
    db = (dep_date - row["retrieved_at"].date()).days
    return db if db >= 0 else None


def _label(p: float) -> str:
    if p <= 25.0:
        return "cheap"
    if p >= 75.0:
        return "expensive"
    return "typical"


def build_price_percentiles(
    rows: Iterable[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Compute per-bucket percentile + cheap/typical/expensive verdict.

    The "latest" price per bucket is the highest-`retrieved_at` observation
    in that bucket; its rank is taken against the entire bucket history
    (including itself). Buckets with `n < 3` are dropped.
    """
    grouped: dict[tuple[str, str, int], list[tuple[datetime, int]]] = defaultdict(list)
    for row in rows:
        db = _days_before(row)
        if db is None:
            continue
        grouped[(_route(row), row["airline"], db)].append(
            (row["retrieved_at"], int(row["price_cents"]))
        )

    buckets: list[dict[str, Any]] = []
    for (route, airline, db), obs in grouped.items():
        if len(obs) < MIN_SAMPLES:
            continue
        latest_t, latest_price = max(obs, key=lambda o: o[0])
        prices = [p for _, p in obs]
        pct = bucketed_percentile(latest_price, prices, min_samples=MIN_SAMPLES)
        if pct is None:
            continue
        buckets.append(
            {
                "route": route,
                "airline": airline,
                "days_before": db,
                "latest_price_cents": latest_price,
                "reference_n": len(prices),
                "percentile": round(pct, 1),
                "label": _label(pct),
            }
        )

    buckets.sort(key=lambda b: (b["route"], b["airline"], -b["days_before"]))
    return {
        "generated_at": (now or datetime.now(timezone.utc))
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "currency": "EUR",
        "min_samples": MIN_SAMPLES,
        "buckets": buckets,
    }
