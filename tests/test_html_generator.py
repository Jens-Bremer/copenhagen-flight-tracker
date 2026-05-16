"""Tests for src/html_generator.py — frontend HTML generation from the slim CSV."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.html_generator import build_calendar, build_metadata, load_rows

FIXTURE = Path(__file__).parent / "fixtures" / "flights_frontend_sample.csv"


def test_load_rows_returns_one_dict_per_csv_row():
    rows = load_rows(str(FIXTURE))
    assert len(rows) > 0
    assert all(isinstance(r, dict) for r in rows)


def test_load_rows_coerces_types():
    rows = load_rows(str(FIXTURE))
    row = rows[0]
    assert isinstance(row["retrieved_at"], datetime)      # tz-aware UTC
    assert row["retrieved_at"].tzinfo is not None
    assert isinstance(row["departure_date"], str)         # kept as ISO string
    assert isinstance(row["departure_at"], datetime)      # naive local
    assert row["departure_at"].tzinfo is None
    assert isinstance(row["arrival_at"], datetime)
    assert isinstance(row["duration_minutes"], int)
    assert isinstance(row["price_cents"], int)
    assert row["price_cents"] > 0


def test_load_rows_skips_blank_lines(tmp_path):
    csv_text = (
        "retrieved_at,departure_date,origin,destination,airline,"
        "departure_at,arrival_at,duration_minutes,price_cents,price_currency\n"
        "2026-05-15T13:45Z,2026-06-19,CPH,AMS,easyJet,"
        "2026-06-19T19:30:00,2026-06-19T21:00:00,90,9200,EUR\n"
        "\n"
    )
    p = tmp_path / "x.csv"
    p.write_text(csv_text)
    assert len(load_rows(str(p))) == 1


def test_load_rows_raises_on_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_rows(str(tmp_path / "nope.csv"))


def test_build_metadata_summarises_input_rows():
    rows = load_rows(str(FIXTURE))
    meta = build_metadata(rows, generated_at=datetime(2026, 5, 15, 23, 47, tzinfo=timezone.utc))
    assert meta["generated_at"] == "2026-05-15T23:47Z"
    assert meta["total_rows"] == len(rows)
    assert meta["date_range"]["from"] <= meta["date_range"]["to"]
    assert "CPH-AMS" in meta["routes"]
    assert "AMS-CPH" in meta["routes"]
    assert "easyJet" in meta["airlines"]


def test_build_metadata_handles_empty_input():
    meta = build_metadata([], generated_at=datetime(2026, 5, 15, 23, 47, tzinfo=timezone.utc))
    assert meta["total_rows"] == 0
    assert meta["date_range"] == {"from": None, "to": None}
    assert meta["routes"] == []
    assert meta["airlines"] == []


def test_build_calendar_min_price_per_route_per_date():
    rows = load_rows(str(FIXTURE))
    cal = build_calendar(rows)
    # CPH-AMS 2026-06-19 has Ryanair at 7800 cents (cheapest)
    assert cal["CPH-AMS"]["2026-06-19"]["min_cents"] == 7800
    # flight_count = distinct (airline, dep_time) pairs across all retrieved_at
    assert cal["CPH-AMS"]["2026-06-19"]["flight_count"] >= 5


def test_build_calendar_empty_input():
    assert build_calendar([]) == {}


def test_build_calendar_separates_directions():
    rows = load_rows(str(FIXTURE))
    cal = build_calendar(rows)
    assert "CPH-AMS" in cal and "AMS-CPH" in cal
    # No CPH-AMS date should leak into AMS-CPH or vice versa
    overlap = set(cal["CPH-AMS"].keys()) & set(cal["AMS-CPH"].keys())
    # CPH-AMS dates and AMS-CPH dates are intentionally disjoint in the fixture
    assert len(overlap) == 0 or all(
        cal["CPH-AMS"][d]["min_cents"] != cal["AMS-CPH"][d]["min_cents"]
        for d in overlap
    )
