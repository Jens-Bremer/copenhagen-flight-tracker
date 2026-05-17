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
    """Per (route, departure_date): min observed price + distinct flight count.

    Flight identity = (airline, dep_time_of_day). Multiple retrieved_at
    snapshots for the same flight collapse into one for the count, but
    every observation participates in the min.
    """
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        route = _route_key(row)
        date = row["departure_date"]
        flight_id = (row["airline"], row["departure_at"].time())
        cell = out.setdefault(route, {}).setdefault(
            date, {"min_cents": row["price_cents"], "_flights": set()}
        )
        cell["min_cents"] = min(cell["min_cents"], row["price_cents"])
        cell["_flights"].add(flight_id)
    # Materialise the count and drop the working set
    for route_cells in out.values():
        for cell in route_cells.values():
            cell["flight_count"] = len(cell.pop("_flights"))
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
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Per (route, departure_date): list of flights with price history.

    A "flight" is identified by (airline, departure_time_of_day). All
    observations for that flight, sorted by retrieved_at, become its
    `history` array. `latest_cents` is the most recent observed price.
    """
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


def build_analysis(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per route: lead-time curve, sweet spot, dow/month means, market trend."""
    if not rows:
        return {}

    # Group prices by (route, days_before)
    by_lead: dict[tuple[str, int], list[int]] = defaultdict(list)
    # Group cheapest-per-departure by (route, dow) and (route, month)
    cheapest_per_dep: dict[tuple[str, str], int] = {}
    # Group cheapest-per-obs-date by (route, obs_date)
    cheapest_per_obs: dict[tuple[str, str], int] = {}
    # Group prices by (route, dow, hour) for the time-of-day heatmap
    by_time: dict[tuple[str, int, int], list[int]] = defaultdict(list)
    # Group prices by (route, dep_date, airline, dep_time, days_before)
    # for normalised price progression
    by_flight: dict[tuple[str, str, str, str], dict[int, list[int]]] = defaultdict(
        lambda: defaultdict(list)
    )
    # All rows per route (for lowest_ever scan)
    rows_by_route: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for row in rows:
        route = _route_key(row)
        rows_by_route[route].append(row)
        dep_date = date_type.fromisoformat(row["departure_date"])
        obs_date = row["retrieved_at"].date().isoformat()
        days_before = (dep_date - row["retrieved_at"].date()).days
        # Skip implausible buckets defensively (should not occur post-#55)
        if days_before < 0:
            continue
        by_lead[(route, days_before)].append(row["price_cents"])
        by_time[
            (route, row["departure_at"].weekday(), row["departure_at"].hour)
        ].append(row["price_cents"])
        dep_time = _hhmm(row["departure_at"])
        by_flight[(route, row["departure_date"], row["airline"], dep_time)][
            days_before
        ].append(row["price_cents"])

        key_dep = (route, row["departure_date"])
        prev_dep = cheapest_per_dep.get(key_dep)
        if prev_dep is None or row["price_cents"] < prev_dep:
            cheapest_per_dep[key_dep] = row["price_cents"]

        key_obs = (route, obs_date)
        prev_obs = cheapest_per_obs.get(key_obs)
        if prev_obs is None or row["price_cents"] < prev_obs:
            cheapest_per_obs[key_obs] = row["price_cents"]

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

    def _quartiles(prices: list[int]) -> tuple[int, int, int, int, int]:
        s = sorted(prices)
        n = len(s)
        return s[0], s[n // 4], s[n // 2], s[(3 * n) // 4], s[-1]

    for route in routes:
        curve_entries = sorted(
            ((db, prices) for (r, db), prices in by_lead.items() if r == route),
            key=lambda x: x[0],
        )

        curve = []
        for db, prices in curve_entries:
            mn, q1, med, q3, mx = _quartiles(prices)
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
                }
            )
        min_obs = config.RELIABLE_MIN_OBSERVATIONS
        reliable = [e for e in curve if e["obs_count"] >= min_obs]
        sweet_spot = (
            min(reliable, key=lambda e: e["mean_cents"])["days_before"]
            if reliable
            else None
        )

        # day_of_week aggregates the per-departure cheapest
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

        # best_time_to_visit: cheapest month/dow from aggregates + lowest ever price
        cheapest_month = (
            min(month_entries, key=lambda m: m["mean_cents"]) if month_entries else {}
        )
        cheapest_dow = (
            min(dow_entries, key=lambda d: d["mean_cents"]) if dow_entries else {}
        )
        route_rows = rows_by_route.get(route, [])
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
        best_time_to_visit = {
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

        out[route] = {
            "lead_time_curve": curve,
            "sweet_spot_days": sweet_spot,
            "day_of_week": dow_entries,
            "month": month_entries,
            "market_trend": trend_entries,
            "time_of_day_matrix": time_matrix,
            "normalized_price_progression": norm_prog,
            "market_direction": market_direction,
            "best_time_to_visit": best_time_to_visit,
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
    # Cheapest-per-(route, departure_date) for weekend-pair join
    cheapest_dep: dict[tuple[str, str], dict[str, Any]] = {}

    for row in rows:
        route = _route_key(row)
        airline = row["airline"]
        bin_lo = _bin_low(row["price_cents"])
        hist_counts[(route, airline, bin_lo)] += 1

        key = (route, row["departure_date"])
        current = cheapest_dep.get(key)
        if current is None or row["price_cents"] < current["price_cents"]:
            cheapest_dep[key] = {
                "airline": airline,
                "dep_time": _hhmm(row["departure_at"]),
                "price_cents": row["price_cents"],
            }

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
        for (route, dep_iso), fri in cheapest_dep.items():
            if route != fri_route:
                continue
            dep_date = date_type.fromisoformat(dep_iso)
            if dep_date.weekday() != 4:  # 4 = Friday
                continue
            sun_iso = (dep_date + timedelta(days=2)).isoformat()
            sun = cheapest_dep.get((sun_route, sun_iso))
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


def _build_app_js() -> str:
    """Concatenate JS source files in order and wrap in an IIFE.

    Each file in JS_SOURCE_DIR (in the order given by JS_FILE_ORDER) declares
    its functions and constants at top level. Concatenation places them all in
    the same IIFE scope, so they can call each other freely without any module
    system. 'use strict' is added once, inside the wrapper.
    """
    parts: list[str] = []
    for filename in JS_FILE_ORDER:
        path = JS_SOURCE_DIR / filename
        if not path.exists():
            raise FileNotFoundError(
                f"required JS source file missing: {path}\n"
                f"Run 'git ls-files frontend/js/' to check the working tree."
            )
        parts.append(path.read_text(encoding="utf-8"))
    body = "\n\n".join(parts)
    return f"(function () {{\n'use strict';\n\n{body}\n}})();"


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
) -> str:
    """Inline assets + JSON blobs into the template. Returns the full HTML string."""
    template = _read_text(TEMPLATE_PATH)
    styles = _read_text(STYLES_PATH)
    chart_js = _read_text(CHART_JS_PATH)
    app_js = _build_app_js()

    return string.Template(template).safe_substitute(
        INLINE_STYLES=styles,
        INLINE_CHART_JS=chart_js,
        INLINE_APP_JS=app_js,
        DATA_METADATA=_safe_json(metadata),
        DATA_CALENDAR=_safe_json(calendar),
        DATA_FLIGHTS=_safe_json(flights),
        DATA_ANALYSIS=_safe_json(analysis),
        DATA_SUMMARY=_safe_json(summary),
    )


def generate(input_path: str, output_path: str) -> int:
    """Read CSV → run analyses → render HTML → write to disk. Returns row count."""
    rows = load_rows(input_path)
    now = datetime.now(timezone.utc)
    metadata = build_metadata(rows, generated_at=now)
    calendar = build_calendar(rows)
    flights = build_flights(rows)
    analysis = build_analysis(rows)
    summary = build_summary(rows)
    html = render_html(
        metadata=metadata,
        calendar=calendar,
        flights=flights,
        analysis=analysis,
        summary=summary,
    )
    Path(output_path).write_text(html, encoding="utf-8")
    return len(rows)
