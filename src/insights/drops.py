"""Recent price-drop / anomaly detection (display-only).

A flight observation counts as a drop when ALL hold:

  1. current price ≤ historical P25 for its (route, airline, days_before)
     bucket over the reference window;
  2. current price is at least `pct_threshold` % below the flight's own
     trailing median over the recent window;
  3. the low price has persisted across ≥ `min_persist` consecutive
     scrapes for that flight identity.

Pure builder. See docs/INSIGHTS_CONTRACT.md for the JSON-blob schema and
config keys.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date as date_type, datetime, timedelta, timezone
from statistics import median
from typing import Any, Iterable

from src.insights.stats import bucketed_percentile

MIN_SAMPLES = 3


@dataclass(frozen=True)
class DropConfig:
    pct_threshold: float = 10.0
    reference_window_days: int = 30
    trailing_window_days: int = 7
    min_persist: int = 2


def _route(row: dict[str, Any]) -> str:
    return f"{row['origin']}-{row['destination']}"


def _days_before(row: dict[str, Any]) -> int | None:
    try:
        dep = date_type.fromisoformat(row["departure_date"])
    except (KeyError, ValueError):
        return None
    db = (dep - row["retrieved_at"].date()).days
    return db if db >= 0 else None


def _flight_id(row: dict[str, Any]) -> tuple[str, str, str, str]:
    """Stable identity for a single flight across scrapes."""
    return (
        _route(row),
        row["airline"],
        row["departure_date"],
        row["departure_at"].strftime("%H:%M"),
    )


def _percentile_25(values: list[int]) -> int | None:
    """Lower-quartile cut. Uses statistics.quantiles when n>=2; fallback to sort."""
    if len(values) < 4:
        return sorted(values)[0] if values else None
    s = sorted(values)
    # method='inclusive' to match build_airline_trends conventions.
    from statistics import quantiles

    return int(quantiles(s, n=4, method="inclusive")[0])


def build_price_drops(
    rows: Iterable[dict[str, Any]],
    config: DropConfig | None = None,
    *,
    now: datetime | None = None,
    min_history_days: int = 14,
) -> dict[str, Any]:
    cfg = config or DropConfig()
    rows = list(rows)
    now_dt = now or datetime.now(timezone.utc)

    distinct_days = {r["retrieved_at"].date() for r in rows}
    history_days = len(distinct_days)
    base = {
        "generated_at": now_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "config": {
            "pct_threshold": cfg.pct_threshold,
            "reference_window_days": cfg.reference_window_days,
            "trailing_window_days": cfg.trailing_window_days,
            "min_persist": cfg.min_persist,
        },
        "history_days": history_days,
    }

    # When we don't have enough history for either persistence OR percentile, bail.
    if history_days < min_history_days:
        return {**base, "insufficient_data": "need_min_14_days_history", "drops": []}

    # Reference window: latest retrieved_at - reference_window_days
    if distinct_days:
        ref_end = max(distinct_days)
    else:
        ref_end = now_dt.date()
    ref_start = ref_end - timedelta(days=cfg.reference_window_days)
    trail_start = ref_end - timedelta(days=cfg.trailing_window_days)

    # Index 1: (route, airline, days_before) -> list of historical prices (within ref window).
    bucket_hist: dict[tuple[str, str, int], list[int]] = defaultdict(list)
    # Index 2: flight_id -> sorted list of (retrieved_at, price, days_before, raw_row).
    per_flight: dict[tuple, list[tuple[datetime, int, int, dict[str, Any]]]] = defaultdict(list)

    for r in rows:
        db = _days_before(r)
        if db is None:
            continue
        rdate = r["retrieved_at"].date()
        if rdate < ref_start:
            continue
        price = int(r["price_cents"])
        bucket_hist[(_route(r), r["airline"], db)].append(price)
        per_flight[_flight_id(r)].append((r["retrieved_at"], price, db, r))

    drops: list[dict[str, Any]] = []
    for fid, obs in per_flight.items():
        obs.sort(key=lambda o: o[0])
        if len(obs) < cfg.min_persist:
            continue
        latest_ts, latest_price, latest_db, latest_row = obs[-1]

        # Persistence: the last `min_persist` observations must all be at the
        # "low" level — defined as within 1% of the latest price.
        tail = obs[-cfg.min_persist :]
        tail_max = max(p for _, p, _, _ in tail)
        tail_min = min(p for _, p, _, _ in tail)
        if tail_max == 0 or (tail_max - tail_min) / tail_max > 0.01:
            continue

        # Trailing median (this flight only, last trailing_window_days incl. latest).
        trailing_prices = [p for ts, p, _, _ in obs if ts.date() >= trail_start]
        if len(trailing_prices) < 2:
            continue
        trailing_med = median(trailing_prices)
        if trailing_med == 0:
            continue
        pct_below = (latest_price - trailing_med) / trailing_med * 100.0
        if pct_below > -cfg.pct_threshold:
            continue  # Not deep enough

        # Reference bucket (≥ MIN_SAMPLES, and value ≤ its P25)
        ref_prices = bucket_hist.get((fid[0], fid[1], latest_db), [])
        if len(ref_prices) < MIN_SAMPLES:
            continue
        p25 = _percentile_25(ref_prices)
        if p25 is None or latest_price > p25:
            continue

        pct = bucketed_percentile(latest_price, ref_prices, min_samples=MIN_SAMPLES)
        drops.append(
            {
                "route": fid[0],
                "airline": fid[1],
                "departure_date": fid[2],
                "departure_at": latest_row["departure_at"].isoformat(),
                "current_price_cents": latest_price,
                "typical_price_cents": int(round(trailing_med)),
                "pct_below": round(pct_below, 1),
                "percentile": None if pct is None else round(pct, 1),
                "persisted_scrapes": len(tail),
            }
        )

    drops.sort(key=lambda d: d["pct_below"])  # most-below first
    return {**base, "drops": drops}
