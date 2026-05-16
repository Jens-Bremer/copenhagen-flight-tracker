"""HTML generator for the flight-tracker frontend.

Reads the slim CSV produced by src/frontend_csv_builder.py and emits a
fully self-contained data/index.html: five JSON blobs + inlined CSS, app
JS, and Chart.js. The browser only renders.

Pure-functional throughout: every transform takes the row list and returns
a value with no side effects. The orchestrator (`generate`) is the only
function that touches the filesystem.

Imports only config + stdlib + json (per CLAUDE.md module contract).
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
            rows.append({
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
            })
    return rows


def _format_minute_z(dt: datetime) -> str:
    """Render '2026-05-15T23:47Z' — Z suffix, minute resolution."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def build_metadata(rows: list[dict[str, Any]], generated_at: datetime) -> dict[str, Any]:
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
