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

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
TEMPLATE_PATH = FRONTEND_DIR / "index.html.template"
STYLES_PATH = FRONTEND_DIR / "styles.css"
APP_JS_PATH = FRONTEND_DIR / "app.js"
CHART_JS_PATH = FRONTEND_DIR / "vendor" / "chart.min.js"

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

    for row in rows:
        route = _route_key(row)
        dep_date = date_type.fromisoformat(row["departure_date"])
        obs_date = row["retrieved_at"].date().isoformat()
        days_before = (dep_date - row["retrieved_at"].date()).days
        # Skip implausible buckets defensively (should not occur post-#55)
        if days_before < 0:
            continue
        by_lead[(route, days_before)].append(row["price_cents"])

        key_dep = (route, row["departure_date"])
        prev_dep = cheapest_per_dep.get(key_dep)
        if prev_dep is None or row["price_cents"] < prev_dep:
            cheapest_per_dep[key_dep] = row["price_cents"]

        key_obs = (route, obs_date)
        prev_obs = cheapest_per_obs.get(key_obs)
        if prev_obs is None or row["price_cents"] < prev_obs:
            cheapest_per_obs[key_obs] = row["price_cents"]

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
        sweet_spot = min(curve, key=lambda e: e["mean_cents"])["days_before"]

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

        out[route] = {
            "lead_time_curve": curve,
            "sweet_spot_days": sweet_spot,
            "day_of_week": dow_entries,
            "month": month_entries,
            "market_trend": trend_entries,
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

    # Weekend pairs for both travel directions:
    # CPH-AMS (Fri) + AMS-CPH (Sun) for the Copenhagen-resident traveller, and
    # AMS-CPH (Fri) + CPH-AMS (Sun) for the Amsterdam-resident traveller.
    for fri_route, sun_route in [("CPH-AMS", "AMS-CPH"), ("AMS-CPH", "CPH-AMS")]:
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
        if fri_route in out:
            out[fri_route]["weekend_pairs"] = pairs[:WEEKEND_PAIRS_TOP_N]
    return out


def _read_text(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"required frontend asset missing: {path}")
    return path.read_text(encoding="utf-8")


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
    app_js = _read_text(APP_JS_PATH)

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
