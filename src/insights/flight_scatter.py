"""Build per-route scatter data for the Live Flight Prices chart.

Each flight is identified by (route, departure_date, airline, departure_at
HH:MM). Only the latest observed price per flight is emitted as a scatter
point, alongside that flight's full observation history (for the hover line).
Stale flights (last observation older than config.STALE_FLIGHT_DAYS days
before `now`) are excluded.

Schema documented in docs/INSIGHTS_CONTRACT.md § DATA_FLIGHT_SCATTER.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

import config

_DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _route(row: dict[str, Any]) -> str:
    return f"{row['origin']}-{row['destination']}"


def build_flight_scatter(
    rows: Iterable[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return scatter data grouped by route.

    For every non-stale flight, emit one scatter point at its latest observed
    price plus its full price history. Observations with a negative
    ``days_before`` (clock skew / departure already passed) are dropped before
    any latest-price or history computation. Returns ``{"routes": {}}`` when
    nothing qualifies. Schema: docs/INSIGHTS_CONTRACT.md § DATA_FLIGHT_SCATTER.
    """
    now = now or datetime.now(timezone.utc)
    generated_at = now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Group observations by flight identity. Identity includes departure_date
    # so each scheduled departure becomes its own scatter point (mirrors the
    # (route, date, airline, dep_time) key used by build_flights).
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        dep_at = row["departure_at"]
        days_before = (dep_at.date() - row["retrieved_at"].date()).days
        if days_before < 0:
            continue
        dep_time = dep_at.strftime("%H:%M")
        key = (_route(row), row["departure_date"], row["airline"], dep_time)
        grouped[key].append(
            {
                "retrieved_at": row["retrieved_at"],
                "days_before": days_before,
                "price_cents": int(row["price_cents"]),
            }
        )

    routes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (route, _dep_date_iso, airline, dep_time), obs in grouped.items():
        obs.sort(key=lambda o: o["retrieved_at"])
        latest = obs[-1]
        latest_retrieved_at = latest["retrieved_at"]
        if (now.date() - latest_retrieved_at.date()).days > config.STALE_FLIGHT_DAYS:
            continue

        # departure_date is identical for every observation in this group.
        dep_date = datetime.fromisoformat(_dep_date_iso).date()

        routes[route].append(
            {
                "airline": airline,
                "dep_time": dep_time,
                "dep_date": _dep_date_iso,
                "dep_dow": _DOW[dep_date.weekday()],
                "days_before": latest["days_before"],
                "price_cents": latest["price_cents"],
                "color": None,
                "history": [
                    {"days_before": o["days_before"], "price_cents": o["price_cents"]}
                    for o in obs
                ],
            }
        )

    for flights in routes.values():
        flights.sort(key=lambda f: (-f["days_before"], f["price_cents"]))

    return {"generated_at": generated_at, "routes": dict(routes)}
