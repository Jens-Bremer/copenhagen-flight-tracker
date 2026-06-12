"""Per-airline price volatility: CV bar chart + rolling std dev of daily minima.

Two outputs per route:
  cv_bars      — one entry per airline sorted by CV descending.
  rolling_stddev — per (airline, obs_date) 14-day rolling std dev of daily min.

Excludes multi-airline strings (comma in name).
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

DEFAULT_MIN_OBS_FOR_CV = 20
ROLLING_WINDOW_DAYS = 14
DEFAULT_MIN_WINDOW_SAMPLES = 7


def _route(row: dict[str, Any]) -> str:
    return f"{row['origin']}-{row['destination']}"


def build_price_volatility_index(
    rows: list[dict[str, Any]],
    *,
    now: datetime | None = None,
    min_obs_for_cv: int = DEFAULT_MIN_OBS_FOR_CV,
    min_window_samples: int = DEFAULT_MIN_WINDOW_SAMPLES,
) -> dict[str, Any]:
    """Return CV bars and rolling std dev of daily minima, grouped by route."""
    gen_at = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Accumulate all prices per (route, airline) and daily minima per (route, airline, obs_date).
    all_prices: dict[tuple[str, str], list[int]] = defaultdict(list)
    daily_min: dict[tuple[str, str, str], int] = {}

    for row in rows:
        airline = row["airline"]
        if "," in airline:
            continue
        route = _route(row)
        price = int(row["price_cents"])
        obs_date = row["retrieved_at"].date().isoformat()

        all_prices[(route, airline)].append(price)

        key = (route, airline, obs_date)
        if key not in daily_min or price < daily_min[key]:
            daily_min[key] = price

    routes = sorted({k[0] for k in all_prices})
    by_route: dict[str, Any] = {}

    for route in routes:
        # --- CV bars ---
        cv_bars: list[dict[str, Any]] = []
        for (r, airline), prices in all_prices.items():
            if r != route or len(prices) < min_obs_for_cv:
                continue
            mean = statistics.fmean(prices)
            std = statistics.stdev(prices)
            cv = std / mean if mean else None
            cv_bars.append(
                {
                    "airline": airline,
                    "cv": round(cv, 4) if cv is not None else None,
                    "mean_cents": round(mean),
                    "std_cents": round(std),
                    "n": len(prices),
                }
            )
        cv_bars.sort(key=lambda b: (b["cv"] is None, -(b["cv"] or 0)))

        # --- Rolling std dev of daily minima ---
        # Group obs_dates per airline, sorted.
        airline_dates: dict[str, list[str]] = defaultdict(list)
        for (r, airline, obs_date) in daily_min:
            if r == route:
                airline_dates[airline].append(obs_date)
        for dates in airline_dates.values():
            dates.sort()

        rolling: list[dict[str, Any]] = []
        for airline, dates in sorted(airline_dates.items()):
            mins = [daily_min[(route, airline, d)] for d in dates]
            for i, (obs_date, daily_min_cents) in enumerate(zip(dates, mins)):
                window = mins[max(0, i - ROLLING_WINDOW_DAYS + 1) : i + 1]
                if len(window) < min_window_samples:
                    continue
                std = statistics.stdev(window) if len(window) >= 2 else 0.0
                rolling.append(
                    {
                        "airline": airline,
                        "obs_date": obs_date,
                        "stddev_cents": round(std),
                        "daily_min_cents": daily_min_cents,
                        "n": len(window),
                    }
                )

        by_route[route] = {
            "cv_bars": cv_bars,
            "rolling_stddev": rolling,
        }

    return {"generated_at": gen_at, "by_route": by_route}
