"""Recent price momentum + historical sweet-spot booking window per route.

Pure builder. See docs/INSIGHTS_CONTRACT.md for the JSON-blob schema.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import date as date_type
from datetime import datetime, timezone
from statistics import median
from typing import Any

from src.insights.stats import linear_trend_slope, trailing_median

DEFAULT_MIN_HISTORY_DAYS = 14
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


def _slope_to_direction(slope_pct_per_day: float | None) -> str | None:
    if slope_pct_per_day is None:
        return None
    if slope_pct_per_day < -0.5:
        return "falling"
    if slope_pct_per_day > 0.5:
        return "rising"
    return "flat"


def _trend_for_window(
    daily_mins: dict[date_type, int], window_days: int
) -> dict[str, Any]:
    """Compute slope/direction/pct_change over the last `window_days` of data."""
    if len(daily_mins) < 2:
        return {"direction": None, "pct_change": None, "sample_days": len(daily_mins)}
    days = sorted(daily_mins.keys())
    cutoff = days[-1]
    window = [d for d in days if (cutoff - d).days < window_days]
    if len(window) < 2:
        return {"direction": None, "pct_change": None, "sample_days": len(window)}
    points = [
        ((d - window[0]).days, float(daily_mins[d]))
        for d in window
    ]
    slope = linear_trend_slope(points)
    median_y = trailing_median([y for _, y in points])
    pct_per_day = (
        (slope / median_y * 100.0) if (slope is not None and median_y) else None
    )
    # Total % change over the window (slope * span / median)
    if slope is not None and median_y:
        span = points[-1][0] - points[0][0]
        pct_change = round(slope * span / median_y * 100.0, 1)
    else:
        pct_change = None
    return {
        "direction": _slope_to_direction(pct_per_day),
        "pct_change": pct_change,
        "sample_days": len(window),
    }


def _sweet_spot(buckets: dict[int, list[int]]) -> dict[str, Any] | None:
    """Return the lead-time bucket with the lowest median price (n>=3)."""
    eligible = [
        (db, prices) for db, prices in buckets.items() if len(prices) >= MIN_SAMPLES
    ]
    if not eligible:
        return None
    eligible.sort(key=lambda kv: median(kv[1]))
    best_db, best_prices = eligible[0]
    return {
        "days_before_low": max(0, best_db - 3),
        "days_before_high": best_db + 3,
        "sample_count": len(best_prices),
        "median_cents": int(median(best_prices)),
    }


def build_price_momentum(
    rows: Iterable[dict[str, Any]],
    *,
    now: datetime | None = None,
    min_history_days: int = DEFAULT_MIN_HISTORY_DAYS,
) -> dict[str, Any]:
    """Build momentum + sweet-spot per route."""
    rows = list(rows)
    distinct_days = {r["retrieved_at"].date() for r in rows}
    history_days = len(distinct_days)
    base = {
        "generated_at": (now or datetime.now(timezone.utc))
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "history_days": history_days,
        "min_history_days": min_history_days,
    }
    if history_days < min_history_days:
        return {**base, "insufficient_data": "need_min_14_days_history", "routes": []}

    # Group by route → daily min price (across all airlines) + lead-time buckets.
    per_route_daily: dict[str, dict[date_type, int]] = defaultdict(dict)
    per_route_buckets: dict[str, dict[int, list[int]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in rows:
        route = _route(row)
        d = row["retrieved_at"].date()
        p = int(row["price_cents"])
        cur = per_route_daily[route].get(d)
        if cur is None or p < cur:
            per_route_daily[route][d] = p
        db = _days_before(row)
        if db is not None:
            per_route_buckets[route][db].append(p)

    routes_out: list[dict[str, Any]] = []
    for route in sorted(per_route_daily.keys()):
        routes_out.append(
            {
                "route": route,
                "recent_7d": _trend_for_window(per_route_daily[route], 7),
                "recent_14d": _trend_for_window(per_route_daily[route], 14),
                "sweet_spot": _sweet_spot(per_route_buckets[route]),
            }
        )
    return {**base, "routes": routes_out}
