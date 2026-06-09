"""HTML generator for the flight-tracker frontend.

Reads the slim CSV produced by src/frontend_csv_builder.py and emits a
fully self-contained frontend/index.html: five JSON blobs + inlined CSS,
app JS, and Chart.js. The browser only renders.

Pure-functional throughout: every transform takes the row list and returns
a value with no side effects. The orchestrator (`generate`) is the only
function that touches the filesystem.

Imports only config + stdlib + json (per CLAUDE.md module contract).
"""

from __future__ import annotations

import csv
import json
import string
from collections import defaultdict
from datetime import date as date_type
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import config
from src.analytics import percentile_rank

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
TEMPLATE_PATH = FRONTEND_DIR / "index.html.template"
STYLES_PATH = FRONTEND_DIR / "styles.css"
CHART_JS_PATH = FRONTEND_DIR / "vendor" / "chart.min.js"
BOXPLOT_JS_PATH = FRONTEND_DIR / "vendor" / "chartjs-chart-boxplot.min.js"
DATE_ADAPTER_JS_PATH = (
    FRONTEND_DIR / "vendor" / "chartjs-adapter-date-fns.bundle.min.js"
)
JS_SOURCE_DIR = FRONTEND_DIR / "js"
JS_FILE_ORDER = [
    "constants.js",
    "state.js",
    "utils.js",
    "data.js",
    "calendar.js",
    "drilldown.js",
    "charts.js",
    "filters.js",
    "main.js",
]

# Minimal JS for airlines.html (no main.js, so no auto-initialization)
JS_FILE_ORDER_AIRLINES = [
    "constants.js",
    "state.js",
    "utils.js",
    "data.js",
    "charts.js",
    "render-airline-trends.js",
]

# ─── CSV loader ──────────────────────────────────────────────────────────────


def _parse_retrieved_at(value: str) -> datetime:
    """Parse '2026-05-15T13:45Z' into a tz-aware UTC datetime."""
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _parse_naive_local(value: str) -> datetime:
    """Parse '2026-06-19T19:30:00' into a naive datetime."""
    return datetime.fromisoformat(value)


def load_rows(path: str) -> list[dict[str, Any]]:
    """Load the slim frontend CSV. Type-coerces every column.

    Raises FileNotFoundError if the file is missing. Skips blank lines.
    Trusts the upstream schema — the writer is the only producer.
    """
    rows: list[dict[str, Any]] = []
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"input file not found: {path}")
    with p.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            if not raw or all((v or "").strip() == "" for v in raw.values()):
                continue
            rows.append(
                {
                    "retrieved_at": _parse_retrieved_at(raw["retrieved_at"]),
                    "departure_date": raw["departure_date"],
                    "origin": raw["origin"],
                    "destination": raw["destination"],
                    "airline": raw["airline"],
                    "departure_at": _parse_naive_local(raw["departure_at"]),
                    "arrival_at": _parse_naive_local(raw["arrival_at"]),
                    "duration_minutes": int(raw["duration_minutes"]),
                    "price_cents": int(raw["price_cents"]),
                    "price_currency": raw["price_currency"],
                }
            )
    return rows


def _format_minute_z(dt: datetime) -> str:
    """Render '2026-05-15T23:47Z' — Z suffix, minute resolution."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def build_metadata(
    rows: list[dict[str, Any]], generated_at: datetime
) -> dict[str, Any]:
    """Top-level metadata: generation timestamp, date range, route + airline lists."""
    if not rows:
        return {
            "generated_at": _format_minute_z(generated_at),
            "date_range": {"from": None, "to": None},
            "total_rows": 0,
            "routes": [],
            "airlines": [],
        }
    dates = sorted({r["departure_date"] for r in rows})
    routes = sorted({f"{r['origin']}-{r['destination']}" for r in rows})
    airlines = sorted({r["airline"] for r in rows})
    return {
        "generated_at": _format_minute_z(generated_at),
        "date_range": {"from": dates[0], "to": dates[-1]},
        "total_rows": len(rows),
        "routes": routes,
        "airlines": airlines,
    }


def _route_key(row: dict[str, Any]) -> str:
    return f"{row['origin']}-{row['destination']}"


def build_calendar(rows: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, int]]]:
    """Per (route, departure_date): latest observed price + distinct flight count.

    Flight identity = (airline, dep_time_of_day). Multiple retrieved_at
    snapshots for the same flight collapse into one; min_cents is the
    cheapest latest price across all distinct flights on that date.
    """
    # Step 1: per (route, date, flight_id) — keep only the most recent price.
    per_flight: dict[tuple, tuple[int, Any]] = {}
    for row in rows:
        key = (
            _route_key(row),
            row["departure_date"],
            row["airline"],
            row["departure_at"].time(),
        )
        existing = per_flight.get(key)
        if existing is None or row["retrieved_at"] >= existing[1]:
            per_flight[key] = (row["price_cents"], row["retrieved_at"])

    # Step 2: aggregate to (route, date) — minimum latest price + flight count.
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for (route, date, _airline, _dep_time), (price, _) in per_flight.items():
        cell = out.setdefault(route, {}).setdefault(
            date, {"min_cents": price, "flight_count": 0}
        )
        if price < cell["min_cents"]:
            cell["min_cents"] = price
        cell["flight_count"] += 1
    return out


def _percentile_from_history(latest_cents: int, history: list[dict]) -> float | None:
    """Rank latest_cents among all history prices using the midpoint-tie algorithm.

    Returns None when fewer than 5 observations exist.
    """
    prices = sorted(h["price_cents"] for h in history)
    return percentile_rank(latest_cents, prices)


def _trajectory_from_history(
    history: list[dict],
) -> tuple[str | None, float | None]:
    """Compute price trajectory from a flight's observation history.

    Compares mean of last 3 observations vs mean of the 3 before that.
    Returns (None, None) when fewer than 6 observations exist.
    """
    if len(history) < 6:
        return None, None
    sorted_h = sorted(history, key=lambda h: h["obs_date"])
    prices = [h["price_cents"] for h in sorted_h]
    prev_mean = sum(prices[-6:-3]) / 3
    recent_mean = sum(prices[-3:]) / 3
    if prev_mean == 0:
        return "stable", 0.0
    pct = round((recent_mean - prev_mean) / prev_mean * 100, 2)
    if pct < -3:
        return "down", pct
    if pct > 3:
        return "up", pct
    return "stable", pct


def _compute_market_direction(obs_prices: dict[str, int]) -> dict[str, Any]:
    """Compute market direction from cheapest-per-obs-date prices.

    Compares the mean of the recent half (or last 7) vs the older half (or prev 7).
    Returns stable/0.0 when fewer than 2 obs dates exist.
    """
    sorted_dates = sorted(obs_prices)
    n = len(sorted_dates)
    if n < 2:
        return {
            "trend": "stable",
            "pct_change": 0.0,
            "label": "Prices stable this week",
        }

    if n >= 14:
        prev_dates = sorted_dates[-14:-7]
        recent_dates = sorted_dates[-7:]
    else:
        mid = n // 2
        prev_dates = sorted_dates[:mid]
        recent_dates = sorted_dates[mid:]

    prev_mean = sum(obs_prices[d] for d in prev_dates) / len(prev_dates)
    recent_mean = sum(obs_prices[d] for d in recent_dates) / len(recent_dates)

    pct = round((recent_mean - prev_mean) / prev_mean * 100, 2) if prev_mean else 0.0

    if pct < -3:
        trend = "down"
        label = f"Prices trending down {abs(pct):.1f}% this week"
    elif pct > 3:
        trend = "up"
        label = f"Prices trending up {pct:.1f}% this week"
    else:
        trend = "stable"
        label = "Prices stable this week"

    return {"trend": trend, "pct_change": pct, "label": label}


def _flight_id(row: dict[str, Any]) -> tuple[str, str]:
    return (row["airline"], row["departure_at"].strftime("%H:%M"))


def _hhmm(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def build_flights(
    rows: list[dict[str, Any]],
    generated_at: datetime | None = None,
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Per (route, departure_date): list of flights with price history.

    A "flight" is identified by (airline, departure_time_of_day). All
    observations for that flight, sorted by retrieved_at, become its
    `history` array. `latest_cents` is the most recent observed price.
    `is_stale` is True when the most recent observation is older than
    config.STALE_FLIGHT_DAYS days before `generated_at`.
    """
    if generated_at is None:
        generated_at = datetime.now(timezone.utc)
    grouped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in rows:
        route = _route_key(row)
        date = row["departure_date"]
        airline, dep_time = _flight_id(row)
        key = (route, date, airline, dep_time)
        bucket = grouped.setdefault(
            key,
            {
                "airline": airline,
                "dep_time": dep_time,
                "arr_time": _hhmm(row["arrival_at"]),
                "duration_minutes": row["duration_minutes"],
                "overnight": row["arrival_at"].date() > row["departure_at"].date(),
                "_obs": [],
            },
        )
        obs_date = row["retrieved_at"].date().isoformat()
        days_before = (row["departure_at"].date() - row["retrieved_at"].date()).days
        bucket["_obs"].append(
            {
                "obs_date": obs_date,
                "price_cents": row["price_cents"],
                "days_before": days_before,
            }
        )

    out: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for (route, date, _a, _t), bucket in grouped.items():
        bucket["_obs"].sort(key=lambda o: o["obs_date"])
        bucket["history"] = bucket.pop("_obs")
        bucket["latest_cents"] = bucket["history"][-1]["price_cents"]
        latest_retrieved_at: str = bucket["history"][-1]["obs_date"]
        bucket["latest_retrieved_at"] = latest_retrieved_at
        days_since = (
            generated_at.date() - date_type.fromisoformat(latest_retrieved_at)
        ).days
        bucket["is_stale"] = days_since > config.STALE_FLIGHT_DAYS
        trajectory, trajectory_pct = _trajectory_from_history(bucket["history"])
        bucket["trajectory"] = trajectory
        bucket["trajectory_pct"] = trajectory_pct
        bucket["percentile"] = _percentile_from_history(
            bucket["latest_cents"], bucket["history"]
        )
        prices = [h["price_cents"] for h in bucket["history"]]
        bucket["historical_mean_cents"] = _mean(prices)
        out.setdefault(route, {}).setdefault(date, []).append(bucket)

    # Stable presentation order: cheapest-latest first
    for route_dates in out.values():
        for flight_list in route_dates.values():
            flight_list.sort(key=lambda f: (f["latest_cents"], f["dep_time"]))
    return out


_DOW_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_MONTH_LABELS = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]


def _mean(values: list[int]) -> int:
    return round(sum(values) / len(values)) if values else 0


def _quartiles(prices: list[int]) -> tuple[int, int, int, int, int]:
    """Return (min, Q1, median, Q3, max) for a non-empty sorted price list."""
    s = sorted(prices)
    n = len(s)
    return s[0], s[n // 4], s[n // 2], s[(3 * n) // 4], s[-1]


def _build_norm_prog_entry(days_before: int, values: list[float]) -> dict[str, Any]:
    """Compute mean, Q1, and Q3 pct_change for a normalized-progression bucket.

    Tolerant of single-observation buckets: when len(values) == 1,
    q1 == q3 == mean. Uses simple index-based quartile (same as _quartiles).
    """
    n = len(values)
    mean_val = round(sum(values) / n, 2)
    if n == 1:
        return {
            "days_before": days_before,
            "mean_pct_change": mean_val,
            "q1_pct_change": mean_val,
            "q3_pct_change": mean_val,
        }
    s = sorted(values)
    q1_val = round(s[n // 4], 2)
    q3_val = round(s[(3 * n) // 4], 2)
    return {
        "days_before": days_before,
        "mean_pct_change": mean_val,
        "q1_pct_change": q1_val,
        "q3_pct_change": q3_val,
    }


def _group_analysis_inputs(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Single-pass grouping of rows into the seven analysis data structures."""
    by_lead: dict[tuple[str, int], list[int]] = defaultdict(list)
    by_lead_airline: dict[tuple[str, int, str], list[int]] = defaultdict(list)
    cheapest_per_dep: dict[tuple[str, str], int] = {}
    cheapest_per_obs: dict[tuple[str, str], int] = {}
    by_time: dict[tuple[str, int, int], list[int]] = defaultdict(list)
    by_flight: dict[tuple[str, str, str, str], dict[int, list[int]]] = defaultdict(
        lambda: defaultdict(list)
    )
    rows_by_route: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for row in rows:
        route = _route_key(row)
        rows_by_route[route].append(row)
        dep_date = date_type.fromisoformat(row["departure_date"])
        obs_date = row["retrieved_at"].date().isoformat()
        days_before = (dep_date - row["retrieved_at"].date()).days
        if days_before < 0:
            continue
        by_lead[(route, days_before)].append(row["price_cents"])
        by_lead_airline[(route, days_before, row["airline"])].append(row["price_cents"])
        by_time[
            (route, row["departure_at"].weekday(), row["departure_at"].hour)
        ].append(row["price_cents"])
        dep_time = _hhmm(row["departure_at"])
        by_flight[(route, row["departure_date"], row["airline"], dep_time)][
            days_before
        ].append(row["price_cents"])
        key_dep = (route, row["departure_date"])
        if key_dep not in cheapest_per_dep or (
            row["price_cents"] < cheapest_per_dep[key_dep]
        ):
            cheapest_per_dep[key_dep] = row["price_cents"]
        key_obs = (route, obs_date)
        if key_obs not in cheapest_per_obs or (
            row["price_cents"] < cheapest_per_obs[key_obs]
        ):
            cheapest_per_obs[key_obs] = row["price_cents"]

    return {
        "by_lead": by_lead,
        "by_lead_airline": by_lead_airline,
        "by_time": by_time,
        "by_flight": by_flight,
        "cheapest_per_dep": cheapest_per_dep,
        "cheapest_per_obs": cheapest_per_obs,
        "rows_by_route": rows_by_route,
    }


def _build_lead_time_curve(
    route: str,
    by_lead: dict[tuple[str, int], list[int]],
    by_lead_airline: dict[tuple[str, int, str], list[int]],
) -> tuple[list[dict[str, Any]], int | None]:
    """Build the lead-time price curve, sweet-spot days, and per-airline breakdown."""
    curve_entries = sorted(
        ((db, prices) for (r, db), prices in by_lead.items() if r == route),
        key=lambda x: x[0],
    )

    # Pre-index per-airline prices for this route only, keyed by (days_before, airline).
    route_airline: dict[tuple[int, str], list[int]] = {
        (d, airline): a_prices
        for (r, d, airline), a_prices in by_lead_airline.items()
        if r == route
    }

    curve = []
    for db, prices in curve_entries:
        mn, q1, med, q3, mx = _quartiles(prices)

        by_airline: dict[str, dict[str, Any]] = {}
        for (d, airline), a_prices in route_airline.items():
            if d != db:
                continue
            _, aq1, amed, aq3, _ = _quartiles(a_prices)
            by_airline[airline] = {
                "median_cents": amed,
                "q1_cents": aq1,
                "q3_cents": aq3,
                "obs_count": len(a_prices),
            }

        curve.append(
            {
                "days_before": db,
                "min_cents": mn,
                "q1_cents": q1,
                "median_cents": med,
                "mean_cents": _mean(prices),
                "q3_cents": q3,
                "max_cents": mx,
                "obs_count": len(prices),
                "by_airline": by_airline,
            }
        )
    min_obs = config.RELIABLE_MIN_OBSERVATIONS
    reliable = [e for e in curve if e["obs_count"] >= min_obs]
    sweet_spot = (
        min(reliable, key=lambda e: e["median_cents"])["days_before"]
        if reliable
        else None
    )
    return curve, sweet_spot


def _build_dow_month(
    route: str,
    cheapest_per_dep: dict[tuple[str, str], int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build day-of-week and month mean-price aggregates for one route."""
    by_dow: dict[int, list[int]] = defaultdict(list)
    by_month: dict[int, list[int]] = defaultdict(list)
    for (r, dep_iso), cents in cheapest_per_dep.items():
        if r != route:
            continue
        d = date_type.fromisoformat(dep_iso)
        by_dow[d.weekday()].append(cents)
        by_month[d.month].append(cents)
    dow_entries = [
        {"dow": dow, "label": _DOW_LABELS[dow], "mean_cents": _mean(vals)}
        for dow, vals in sorted(by_dow.items())
    ]
    month_entries = [
        {"month": m, "label": _MONTH_LABELS[m - 1], "mean_cents": _mean(vals)}
        for m, vals in sorted(by_month.items())
    ]
    return dow_entries, month_entries


def _build_best_time_to_visit(
    month_entries: list[dict[str, Any]],
    dow_entries: list[dict[str, Any]],
    route_rows: list[dict[str, Any]],
    route: str,
) -> dict[str, Any]:
    """Compute cheapest month, day-of-week, and all-time lowest price for a route."""
    cheapest_month = (
        min(month_entries, key=lambda m: m["mean_cents"]) if month_entries else {}
    )
    cheapest_dow = (
        min(dow_entries, key=lambda d: d["mean_cents"]) if dow_entries else {}
    )
    if route_rows:
        min_row = min(route_rows, key=lambda r: r["price_cents"])
        lowest_ever: dict[str, Any] = {
            "price_cents": min_row["price_cents"],
            "route": route,
            "departure_date": min_row["departure_date"],
            "airline": min_row["airline"],
        }
    else:
        lowest_ever = {}
    return {
        "cheapest_month": {
            "label": cheapest_month.get("label", ""),
            "mean_cents": cheapest_month.get("mean_cents", 0),
        },
        "cheapest_dow": {
            "label": cheapest_dow.get("label", ""),
            "mean_cents": cheapest_dow.get("mean_cents", 0),
        },
        "lowest_ever": lowest_ever,
    }


def build_analysis(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per route: lead-time curve, sweet spot, dow/month means, market trend."""
    if not rows:
        return {}

    groups = _group_analysis_inputs(rows)
    by_lead = groups["by_lead"]
    by_lead_airline = groups["by_lead_airline"]
    by_time = groups["by_time"]
    by_flight = groups["by_flight"]
    cheapest_per_dep = groups["cheapest_per_dep"]
    cheapest_per_obs = groups["cheapest_per_obs"]
    rows_by_route = groups["rows_by_route"]

    # Normalised progression: per flight, express each obs as % change from the
    # oldest observation; aggregate across all flights per (route, days_before).
    pct_by_days: dict[tuple[str, int], list[float]] = defaultdict(list)
    for (route, _dep, _air, _time), obs_by_days in by_flight.items():
        if len(obs_by_days) < 2:
            continue
        sorted_days = sorted(
            obs_by_days.keys(), reverse=True
        )  # oldest = highest days_before
        base = _mean(obs_by_days[sorted_days[0]])
        if base == 0:
            continue
        for db in sorted_days:
            pct = (_mean(obs_by_days[db]) - base) / base * 100
            pct_by_days[(route, db)].append(pct)

    # Build lead-time curve per route, sorted by days_before
    routes = sorted({k[0] for k in by_lead})
    out: dict[str, dict[str, Any]] = {}

    for route in routes:
        curve, sweet_spot = _build_lead_time_curve(route, by_lead, by_lead_airline)

        dow_entries, month_entries = _build_dow_month(route, cheapest_per_dep)

        trend_entries = sorted(
            (
                {"obs_date": od, "min_cents": cents}
                for (r, od), cents in cheapest_per_obs.items()
                if r == route
            ),
            key=lambda e: e["obs_date"],
        )

        time_matrix = sorted(
            (
                {"dow": dow, "hour": hour, "mean_cents": _mean(prices)}
                for (r, dow, hour), prices in by_time.items()
                if r == route
            ),
            key=lambda e: (e["dow"], e["hour"]),
        )

        norm_prog = sorted(
            (
                _build_norm_prog_entry(db, v)
                for (r, db), v in pct_by_days.items()
                if r == route
            ),
            key=lambda e: e["days_before"],
        )

        # market_direction: compare cheapest-per-obs price across recent vs older dates
        obs_prices_for_route = {
            od: cents for (r, od), cents in cheapest_per_obs.items() if r == route
        }
        market_direction = _compute_market_direction(obs_prices_for_route)

        best_time = _build_best_time_to_visit(
            month_entries, dow_entries, rows_by_route.get(route, []), route
        )

        out[route] = {
            "lead_time_curve": curve,
            "sweet_spot_days": sweet_spot,
            "day_of_week": dow_entries,
            "month": month_entries,
            "market_trend": trend_entries,
            "time_of_day_matrix": time_matrix,
            "normalized_price_progression": norm_prog,
            "market_direction": market_direction,
            "best_time_to_visit": best_time,
        }
    return out


BIN_WIDTH_CENTS = 500  # €5 bins
WEEKEND_PAIRS_TOP_N = 5


def _bin_low(cents: int) -> int:
    return (cents // BIN_WIDTH_CENTS) * BIN_WIDTH_CENTS


def build_summary(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per route: airline histogram + top-5 Fri/Sun weekend pairs."""
    if not rows:
        return {}

    # Histogram bins keyed by (route, airline, bin_low)
    hist_counts: dict[tuple[str, str, int], int] = defaultdict(int)
    # Step 1: latest price per distinct flight (route, date, airline, dep_time).
    # Mirrors build_calendar: multiple snapshots of the same flight collapse to
    # the most recent observation before we compare prices across flights.
    latest_per_flight: dict[tuple[str, str, str, Any], dict[str, Any]] = {}

    for row in rows:
        route = _route_key(row)
        airline = row["airline"]
        bin_lo = _bin_low(row["price_cents"])
        hist_counts[(route, airline, bin_lo)] += 1

        key = (route, row["departure_date"], airline, row["departure_at"].time())
        current = latest_per_flight.get(key)
        if current is None or row["retrieved_at"] >= current["_retrieved_at"]:
            latest_per_flight[key] = {
                "airline": airline,
                "dep_time": _hhmm(row["departure_at"]),
                "price_cents": row["price_cents"],
                "_retrieved_at": row["retrieved_at"],
            }

    # Step 2: cheapest latest flight per (route, departure_date).
    # This ensures weekend pairs always show the best available price on each leg.
    latest_dep: dict[tuple[str, str], dict[str, Any]] = {}
    for (route, dep_iso, _airline, _dep_time), info in latest_per_flight.items():
        dep_key = (route, dep_iso)
        current = latest_dep.get(dep_key)
        if current is None or info["price_cents"] < current["price_cents"]:
            latest_dep[dep_key] = info

    out: dict[str, dict[str, Any]] = {}
    routes = sorted({k[0] for k in hist_counts})
    for route in routes:
        # Group histogram by airline, sort bins ascending
        histogram: dict[str, list[dict[str, int]]] = {}
        for (r, airline, bin_lo), count in hist_counts.items():
            if r != route:
                continue
            histogram.setdefault(airline, []).append(
                {
                    "bin_low": bin_lo,
                    "bin_high": bin_lo + BIN_WIDTH_CENTS,
                    "count": count,
                }
            )
        for bins in histogram.values():
            bins.sort(key=lambda b: b["bin_low"])
        out[route] = {"histogram": histogram, "weekend_pairs": []}

    # Weekend pairs: for every route, pair Friday departures with the reverse
    # route's Sunday return (origin↔destination swapped, +2 days).
    # This generalises across any set of routes, not just CPH-AMS ↔ AMS-CPH.
    for fri_route in list(out.keys()):
        # Derive reverse route by swapping the origin and destination.
        parts = fri_route.split("-", 1)
        if len(parts) != 2:
            continue
        sun_route = f"{parts[1]}-{parts[0]}"
        if sun_route not in out:
            continue
        pairs: list[dict[str, Any]] = []
        for (route, dep_iso), fri in latest_dep.items():
            if route != fri_route:
                continue
            dep_date = date_type.fromisoformat(dep_iso)
            if dep_date.weekday() != 4:  # 4 = Friday
                continue
            sun_iso = (dep_date + timedelta(days=2)).isoformat()
            sun = latest_dep.get((sun_route, sun_iso))
            if sun is None:
                continue
            pairs.append(
                {
                    "fri_date": dep_iso,
                    "fri_airline": fri["airline"],
                    "fri_dep": fri["dep_time"],
                    "fri_cents": fri["price_cents"],
                    "sun_date": sun_iso,
                    "sun_airline": sun["airline"],
                    "sun_dep": sun["dep_time"],
                    "sun_cents": sun["price_cents"],
                    "total_cents": fri["price_cents"] + sun["price_cents"],
                }
            )
        pairs.sort(key=lambda p: p["total_cents"])
        out[fri_route]["weekend_pairs"] = pairs[:WEEKEND_PAIRS_TOP_N]
    return out


def _read_text(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"required frontend asset missing: {path}")
    return path.read_text(encoding="utf-8")


def _build_app_js(
    file_order: list[str] | None = None, expose_functions: list[str] | None = None
) -> str:
    """Concatenate JS source files in order and wrap in an IIFE.

    Each file in JS_SOURCE_DIR (in the order given by file_order or JS_FILE_ORDER)
    declares its functions and constants at top level. Concatenation places them all
    in the same IIFE scope, so they can call each other freely without any module
    system. 'use strict' is added once, inside the wrapper.

    If expose_functions is provided, those functions are attached to window at the end.
    """
    if file_order is None:
        file_order = JS_FILE_ORDER

    parts: list[str] = []
    for filename in file_order:
        path = JS_SOURCE_DIR / filename
        if not path.exists():
            raise FileNotFoundError(
                f"required JS source file missing: {path}\n"
                f"Run 'git ls-files frontend/js/' to check the working tree."
            )
        parts.append(path.read_text(encoding="utf-8"))
    body = "\n\n".join(parts)

    # If functions need to be exposed to window, add that at the end
    expose_lines = ""
    if expose_functions:
        window_assigns = (f"window.{func} = {func};" for func in expose_functions)
        expose_lines = "\n".join(window_assigns)
        expose_lines = "\n" + expose_lines

    return f"(function () {{\n'use strict';\n\n{body}{expose_lines}\n}})();"


def build_airline_trends(rows: list[dict]) -> dict:
    """
    Build per-airline price progression by days_before across two routes.

    Args:
        rows: Observations with keys: airline, origin, destination, retrieved_at,
            departure_date, price_cents

    Returns:
        {
          "CPH-AMS": [
            {
              "airline": "KLM",
              "color": "#00A1DE",
              "series": [
                {"days_before": 168, "median_cents": 5200, "p25_cents": 4800,
                 "p75_cents": 5600, "sample_count": 3},
                ...
              ]
            },
            ...
          ],
          "AMS-CPH": [ ... ]
        }
    """
    import statistics

    # Group by (airline, route, days_before)
    grouped = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for row in rows:
        route = _route_key(row)
        airline = row["airline"]
        price_cents = row["price_cents"]
        dep_date = date_type.fromisoformat(row["departure_date"])
        days_before = (dep_date - row["retrieved_at"].date()).days
        if days_before < 0:
            continue
        grouped[route][airline][days_before].append(price_cents)

    # Filter: keep only airlines with ≥3 total observations per route
    result = {}
    for route in sorted(grouped.keys()):
        airlines_data = []
        for airline in sorted(grouped[route].keys()):
            days_dict = grouped[route][airline]
            total_obs = sum(len(v) for v in days_dict.values())
            if total_obs < 3:
                continue

            # Build series: one point per days_before bucket
            series = []
            for days_before in sorted(days_dict.keys(), reverse=True):
                prices = sorted(days_dict[days_before])
                # Handle single-observation case: quantiles require ≥2 data points
                if len(prices) == 1:
                    p25 = prices[0]
                    median = prices[0]
                    p75 = prices[0]
                else:
                    median = statistics.median(prices)
                    # method='inclusive' returns actual data points, not interpolated
                    quantiles = statistics.quantiles(prices, n=4, method="inclusive")
                    p25 = quantiles[0]
                    p75 = quantiles[2]
                series.append(
                    {
                        "days_before": days_before,
                        "median_cents": int(median),
                        "p25_cents": int(p25),
                        "p75_cents": int(p75),
                        "sample_count": len(prices),
                    }
                )

            # Get color from AIRLINE_COLORS or fallback to hash
            color = get_airline_color(airline)

            airlines_data.append(
                {
                    "airline": airline,
                    "color": color,
                    "series": series,
                }
            )

        result[route] = airlines_data

    return result


def build_airline_matrix(rows: list[dict]) -> dict:
    """
    Build weekly seasonality matrix per airline/route.

    For each (airline, route), compute relative price index per cell
    (buy_weekday x travel_weekday) where travel_weekday is Fri/Sat/Sun only.

    Args:
        rows: Observations with keys: airline, origin, destination, retrieved_at,
            departure_date, price_cents

    Returns:
        {
          "CPH-AMS": [
            {
              "airline": "KLM",
              "color": "#00A1DE",
              "matrix": {
                "Friday": {
                  "Monday": {"category": "low", "index": -0.032, "n": 8},
                  "Tuesday": None,
                  ...
                },
                "Saturday": { ... },
                "Sunday": { ... }
              }
            },
            ...
          ],
          "AMS-CPH": [ ... ]
        }

        Cell is None when fewer than 3 observations.
    """
    import statistics

    TRAVEL_DAYS = {4: "Friday", 5: "Saturday", 6: "Sunday"}
    BUY_DAY_NAMES = [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    ]

    # Group prices by (route, airline, buy_weekday, travel_weekday)
    grouped: dict = defaultdict(
        lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    )
    for row in rows:
        dep_weekday = date_type.fromisoformat(row["departure_date"]).weekday()
        if dep_weekday not in TRAVEL_DAYS:
            continue
        route = _route_key(row)
        airline = row["airline"]
        buy_weekday = row["retrieved_at"].weekday()
        grouped[route][airline][buy_weekday][dep_weekday].append(row["price_cents"])

    result: dict = {}
    for route in sorted(grouped.keys()):
        airlines_data = []
        for airline in sorted(grouped[route].keys()):
            buy_day_map = grouped[route][airline]

            # Collect all prices for overall median
            all_prices = [
                p
                for buy_prices in buy_day_map.values()
                for cell_prices in buy_prices.values()
                for p in cell_prices
            ]
            if len(all_prices) < 3:
                continue

            overall_median = statistics.median(all_prices)

            matrix: dict = {}
            for travel_name in TRAVEL_DAYS.values():
                travel_wd = next(k for k, v in TRAVEL_DAYS.items() if v == travel_name)
                day_cells: dict = {}
                for buy_wd, buy_name in enumerate(BUY_DAY_NAMES):
                    prices = buy_day_map.get(buy_wd, {}).get(travel_wd, [])
                    if len(prices) < 3:
                        day_cells[buy_name] = None
                        continue
                    cell_median = statistics.median(prices)
                    index = (cell_median - overall_median) / overall_median
                    abs_index = abs(index)
                    if abs_index <= 0.01:
                        category = "no"
                    elif abs_index <= 0.05:
                        category = "low"
                    elif abs_index <= 0.15:
                        category = "med"
                    else:
                        category = "high"
                    day_cells[buy_name] = {
                        "category": category,
                        "index": round(index, 4),
                        "n": len(prices),
                    }
                matrix[travel_name] = day_cells

            airlines_data.append(
                {
                    "airline": airline,
                    "color": get_airline_color(airline),
                    "matrix": matrix,
                }
            )

        result[route] = airlines_data

    return result


def get_airline_color(airline: str) -> str:
    """
    Get colour for airline from locked AIRLINE_COLORS, or deterministic hash fallback.
    """
    AIRLINE_COLORS = {
        "KLM": "#00A1DE",
        "Norwegian": "#D4001E",
        "easyJet": "#FF6600",
        "Scandinavian Airlines": "#003087",
        "SAS": "#003087",
        "Ryanair": "#F1C40F",
        "Finnair": "#00386F",
    }
    if airline in AIRLINE_COLORS:
        return AIRLINE_COLORS[airline]

    # Fallback: MD5 hash → first 6 chars (not for security, just color generation)
    import hashlib

    hash_val = hashlib.md5(airline.encode(), usedforsecurity=False).hexdigest()[:6]
    return f"#{hash_val}"


def _safe_json(obj: Any) -> str:
    """Serialise *obj* for embedding inside <script type="application/json">.

    Defeats a `</script>` injection in any string field by replacing the byte
    sequence `</` with `<\\/`, which JSON still parses identically. Without
    this an attacker-controlled airline name could break out of the JSON
    context and execute JS in the page.
    """
    return json.dumps(obj, separators=(",", ":")).replace("</", "<\\/")


def render_html(
    metadata: dict[str, Any],
    calendar: dict[str, Any],
    flights: dict[str, Any],
    analysis: dict[str, Any],
    summary: dict[str, Any],
    airline_trends: dict[str, Any] | None = None,
    airline_matrix: dict[str, Any] | None = None,
    inline_data: bool = False,
) -> tuple[str, str]:
    """Inline assets + JSON blobs into templates. Returns (index_html, airlines_html).

    When *inline_data* is True the JSON blobs are substituted directly into
    the ``<script type="application/json">`` elements in the templates, producing
    fully self-contained HTML files (the original behaviour).

    When *inline_data* is False (the default) the blob placeholders are replaced
    with empty strings, so the browser's ``loadData()`` in data.js will fetch
    ``data.json`` instead.  The caller is responsible for writing that file (see
    :func:`generate`).
    """
    if airline_trends is None:
        airline_trends = {}
    if airline_matrix is None:
        airline_matrix = {}

    template = _read_text(TEMPLATE_PATH)
    styles = _read_text(STYLES_PATH)
    chart_js = _read_text(CHART_JS_PATH)
    date_adapter_js = _read_text(DATE_ADAPTER_JS_PATH)
    boxplot_js = _read_text(BOXPLOT_JS_PATH)
    app_js = _build_app_js()
    app_js_airlines = _build_app_js(
        JS_FILE_ORDER_AIRLINES, expose_functions=["renderAirlineTrends"]
    )

    # Load header, footer
    header_template = _read_text(FRONTEND_DIR / "header.html")
    footer_template = _read_text(FRONTEND_DIR / "footer.html")
    airlines_template = _read_text(FRONTEND_DIR / "airlines.html.template")

    if inline_data:
        data_metadata = _safe_json(metadata)
        data_calendar = _safe_json(calendar)
        data_flights = _safe_json(flights)
        data_analysis = _safe_json(analysis)
        data_summary = _safe_json(summary)
        data_airline_trends = _safe_json(airline_trends)
        data_airline_matrix = _safe_json(airline_matrix)
    else:
        data_metadata = ""
        data_calendar = ""
        data_flights = ""
        data_analysis = ""
        data_summary = ""
        data_airline_trends = ""
        data_airline_matrix = ""

    # Render index.html
    index_html = string.Template(template).safe_substitute(
        INLINE_STYLES=styles,
        INLINE_HEADER=header_template,
        INLINE_CHART_JS=chart_js,
        INLINE_DATE_ADAPTER_JS=date_adapter_js,
        INLINE_BOXPLOT_JS=boxplot_js,
        INLINE_APP_JS=app_js,
        INLINE_FOOTER=footer_template,
        DATA_METADATA=data_metadata,
        DATA_CALENDAR=data_calendar,
        DATA_FLIGHTS=data_flights,
        DATA_ANALYSIS=data_analysis,
        DATA_SUMMARY=data_summary,
    )

    # Render airlines.html (render function is in app_js_airlines)
    airlines_html = string.Template(airlines_template).safe_substitute(
        INLINE_STYLES=styles,
        INLINE_HEADER=header_template,
        INLINE_FOOTER=footer_template,
        INLINE_CHART_JS=chart_js,
        INLINE_APP_JS=app_js_airlines,
        RENDER_AIRLINE_TRENDS="",
        DATA_AIRLINE_TRENDS=data_airline_trends,
        DATA_AIRLINE_MATRIX=data_airline_matrix,
    )

    return index_html, airlines_html


def generate(input_path: str, output_path: str, inline_data: bool = False) -> int:
    """Read CSV → run analyses → render HTML → write to disk. Returns row count.

    When *inline_data* is False (default) the five JSON blobs are written to a
    sibling file ``data.json`` next to *output_path* and the HTML references
    them via ``fetch('data.json')``.  When *inline_data* is True the blobs are
    embedded directly in the HTML (the original behaviour, suitable for
    offline / USB use).
    """
    rows = load_rows(input_path)
    now = datetime.now(timezone.utc)
    metadata = build_metadata(rows, generated_at=now)
    calendar = build_calendar(rows)
    flights = build_flights(rows, generated_at=now)
    analysis = build_analysis(rows)
    summary = build_summary(rows)
    airline_trends = build_airline_trends(rows)
    airline_matrix = build_airline_matrix(rows)

    if not inline_data:
        # Write the five blobs to data.json in the same directory as output_path
        data_payload = {
            "metadata": metadata,
            "calendar": calendar,
            "flights": flights,
            "analysis": analysis,
            "summary": summary,
            "airline_trends": airline_trends,
            "airline_matrix": airline_matrix,
        }
        data_json_path = Path(output_path).parent / "data.json"
        data_json_path.write_text(
            json.dumps(data_payload, separators=(",", ":")), encoding="utf-8"
        )

    index_html, airlines_html = render_html(
        metadata=metadata,
        calendar=calendar,
        flights=flights,
        analysis=analysis,
        summary=summary,
        airline_trends=airline_trends,
        airline_matrix=airline_matrix,
        inline_data=inline_data,
    )
    Path(output_path).write_text(index_html, encoding="utf-8")

    # Write airlines.html to the same directory as output_path
    airlines_path = Path(output_path).parent / "airlines.html"
    airlines_path.write_text(airlines_html, encoding="utf-8")

    return len(rows)
